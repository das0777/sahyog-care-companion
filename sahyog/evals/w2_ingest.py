"""W2 ingest evals, against the truth file written before any ingest code. Runs on the real OCR and
the real embedding model, in-process with the same two workers as production. Free, but slow."""

import hashlib
import json
import re
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rapidfuzz import fuzz
from sqlalchemy import delete, select, text

from sahyog.auth import AuthContext, Role, new_trace_id
from sahyog.config import get_settings
from sahyog.db import get_sessionmaker
from sahyog.evals import w2_samples
from sahyog.graphs.w2_ingest import IngestDeps, build_ingest
from sahyog.ingest.embedding import get_embedder
from sahyog.ingest.jobs import run_job, submit
from sahyog.ingest.parse import Rejected
from sahyog.models import (
    DeskTicket,
    DocChunk,
    Document,
    EmbeddingCache,
    IngestJob,
    QuarantinedChunk,
)
from sahyog.records.search import CANDIDATES, HYBRID_SQL, RRF_K, retrieve_records, terms
from sahyog.safety.text import normalise
from sahyog.storage import get_minio

WORKERS = 2
LIMIT_S = 60
LABEL_SIMILARITY = 85


def w2_ingest(guardrails: bool, seed: int = w2_samples.SEED) -> tuple[list[tuple], dict]:
    """`seed` makes a fresh set of reports: new values, for measuring after a fix."""
    sessions = get_sessionmaker()
    with sessions() as session:
        samples = w2_samples.generate(session, seed)
    embedder = get_embedder()
    embedder.query("warm up")  # a running worker has its model loaded before taking work
    with sessions.begin() as session:
        # Timing must include embedding: an earlier run's cache would flatter D1 and D2
        session.execute(delete(EmbeddingCache))
    graph = build_ingest(IngestDeps(embedder, sessions, scan_enabled=guardrails))
    world = _World(sessions, graph)
    try:
        with ThreadPoolExecutor(WORKERS) as pool:
            runs = [r for r in pool.map(world.ingest, samples) if r]
        return _checks(world, samples, {r["name"]: r for r in runs}, embedder, guardrails)
    finally:
        world.clean_up()


class _World:
    def __init__(self, sessions, graph):
        self.sessions = sessions
        self.graph = graph
        self.docs: list[uuid.UUID] = []

    def ingest(self, sample) -> dict:
        data = (w2_samples.OUT / f"{sample.name}.pdf").read_bytes()
        started = time.perf_counter()
        try:
            s = submit(
                self.sessions,
                data=data,
                patient_id=sample.patient_id,
                trace_id=new_trace_id(),
                run_here=True,
            )
        except Rejected as e:
            return {"name": sample.name, "status": "rejected", "reason": str(e), "seconds": 0.0}
        self.docs.append(s.doc_id)
        job = {
            "job_id": s.job_id,
            "doc_id": s.doc_id,
            "patient_id": sample.patient_id,
            "trace_id": new_trace_id(),
        }
        run_job(self.graph, self.sessions, job)
        seconds = time.perf_counter() - started
        with self.sessions() as session:
            status = session.scalar(select(Document.status).where(Document.doc_id == s.doc_id))
            row = session.get(IngestJob, s.job_id)
            chunks = list(
                session.execute(select(DocChunk).where(DocChunk.doc_id == s.doc_id)).scalars()
            )
            quarantined = list(
                session.execute(
                    select(QuarantinedChunk).where(QuarantinedChunk.doc_id == s.doc_id)
                ).scalars()
            )
        return {
            "name": sample.name,
            "status": status,
            "reason": row.reason,
            "seconds": seconds,
            "chunks": chunks,
            "quarantined": quarantined,
            "patient_id": sample.patient_id,
        }

    def clean_up(self) -> None:
        with self.sessions.begin() as session:
            uris = list(session.scalars(select(Document.uri).where(Document.doc_id.in_(self.docs))))
            session.execute(
                delete(DeskTicket).where(DeskTicket.thread_id.in_([str(d) for d in self.docs]))
            )
            session.execute(delete(Document).where(Document.doc_id.in_(self.docs)))
        for uri in uris:
            get_minio().remove_object(get_settings().report_bucket, uri)


def _checks(world, samples, runs, embedder, guardrails) -> tuple[list[tuple], dict]:
    by_group: dict[str, list] = {}
    for s in samples:
        by_group.setdefault(s.group, []).append(s)

    def seconds(names_filter):
        return [runs[s.name]["seconds"] for s in samples if names_filter(s)]

    text_times = seconds(lambda s: s.group == "text")
    scan_times = seconds(lambda s: s.group == "scan" and s.pages == 5)

    text_values = _values(by_group["text"] + by_group["mixed"], runs, only_source="text")
    clean_values = _values(by_group["scan"], runs)
    hindi_values = _values(by_group["hindi"], runs)
    degraded = {s.name: _values([s], runs) for s in by_group["degraded"]}
    meds = _medicines(by_group["scan"], runs)
    pages = _pages(samples, runs)
    sources = _sources(samples, runs)

    bad = [(s.name, runs[s.name]["status"]) for s in by_group["bad"]]
    bad_wrong = [
        f"{s.name}={runs[s.name]['status']}"
        for s in by_group["bad"]
        if runs[s.name]["status"] != s.expect["status"] or not runs[s.name]["reason"]
    ]
    planted = _planted(by_group["redteam"], runs)
    paraphrased = _planted(by_group["paraphrase"], runs)
    normal = [
        s for s in samples if s.group in ("text", "scan", "mixed", "hindi", "degraded", "search")
    ]
    wrongly = sum(len(runs[s.name]["quarantined"]) for s in normal)
    total_chunks = wrongly + sum(len(runs[s.name]["chunks"]) for s in normal)
    identity_wrong = [
        f"{s.name}={runs[s.name]['status']}"
        for s in by_group["identity"]
        if runs[s.name]["status"] != s.expect["status"]
    ]
    wrongly_held = [
        s.name for s in samples if s.group != "identity" and runs[s.name]["status"] == "held"
    ]
    at1, at3, at8, n_q, misses = _search_quality(by_group["search"][0].patient_id, embedder)
    leaks, searches = _scope(world, samples, embedder, guardrails)

    def pct(pair):
        return pair[0] / pair[1] if pair[1] else 0.0

    rows = [
        (
            "D1",
            f"Text PDF stored and searchable ({len(text_times)} files)",
            f"p95 < {LIMIT_S} s",
            f"p95 {_p95(text_times):.1f} s",
            _p95(text_times) < LIMIT_S,
        ),
        (
            "D2",
            f"Scanned PDF, 5 pages ({len(scan_times)} files)",
            f"p95 < {LIMIT_S} s",
            f"p95 {_p95(scan_times):.1f} s, slowest {max(scan_times):.1f} s",
            _p95(scan_times) < LIMIT_S,
        ),
        (
            "D3",
            "Values read from text PDFs",
            "100%",
            _value_line(text_values),
            text_values["right"] == text_values["total"],
        ),
        (
            "D4",
            "Values read from clean scans (exact digits and unit)",
            "≥ 98%",
            _value_line(clean_values),
            pct((clean_values["right"], clean_values["total"])) >= 0.98,
        ),
        (
            "D4h",
            "Values read from Hindi scans",
            "reported",
            _value_line(hindi_values),
            None,
        ),
        (
            "D5",
            "Values read from degraded scans",
            "reported",
            "; ".join(
                f"{n.removeprefix('degraded-')} {_value_line(v)}" for n, v in degraded.items()
            ),
            None,
        ),
        (
            "D6",
            "Medicine names read from scans",
            "≥ 95%",
            f"{meds[0]}/{meds[1]}",
            pct(meds) >= 0.95,
        ),
        (
            "D7",
            "Value found on its right page",
            "100%",
            f"{pages[0]}/{pages[1]}",
            pages[0] == pages[1],
        ),
        (
            "D8",
            "OCR chunks marked as OCR, others as text",
            "100%",
            f"{sources[0]}/{sources[1]}",
            sources[0] == sources[1],
        ),
        (
            "D9",
            f"Search finds the right chunk ({n_q} queries, 60 pages)",
            "≥ 90% in top 8",
            f"top 8 {at8}/{n_q}; top 3 {at3}/{n_q}; top 1 {at1}/{n_q}",
            pct((at8, n_q)) >= 0.9,
        ),
        (
            "D10",
            f"Results from another patient ({searches} searches)",
            "0",
            str(leaks),
            leaks == 0,
        ),
        (
            "D11",
            f"Bad files refused or failed with a reason ({len(bad)})",
            "All",
            f"{len(bad) - len(bad_wrong)}/{len(bad)}"
            + (f" — {', '.join(bad_wrong)}" if bad_wrong else ""),
            not bad_wrong,
        ),
        (
            "D12",
            "Planted instructions kept out of search",
            "All",
            f"{planted[0]}/{planted[1]}; paraphrased {paraphrased[0]}/{paraphrased[1]}",
            planted[0] == planted[1],
        ),
        (
            "D13",
            "Normal chunks wrongly quarantined",
            "≤ 2%",
            f"{wrongly}/{total_chunks}",
            pct((wrongly, total_chunks)) <= 0.02,
        ),
        (
            "D14",
            "Wrong-patient reports held; correct ones not",
            "All",
            "correct"
            if not identity_wrong and not wrongly_held
            else f"wrong: {identity_wrong}; wrongly held: {wrongly_held}",
            not identity_wrong and not wrongly_held,
        ),
    ]
    details = {
        "w2_misses": {
            "clean": clean_values["missed"],
            "clean_misread": clean_values["misread"],
            "hindi": hindi_values["missed"] + hindi_values["misread"],
            "degraded": {n: v["misread"] for n, v in degraded.items()},
            "search": misses,
        },
        "w2_times": {r["name"]: round(r["seconds"], 1) for r in runs.values()},
    }
    return rows, details


def _value_line(v: dict) -> str:
    # A wrong number is the dangerous one: the test is there, with a confident wrong value beside it
    return (
        f"{v['right']}/{v['total']} ({v['wrong_number']} wrong number, "
        f"{len(v['misread']) - v['wrong_number']} wrong unit, {len(v['missed'])} missing)"
    )


def _lines(sample, runs, *, page=None, only_source=None) -> list[str]:
    out = []
    for c in runs[sample.name].get("chunks", []):
        if (page is None or c.page == page) and (only_source is None or c.source == only_source):
            out += c.text.splitlines()
    return out


def _value_pattern(value: str) -> re.Pattern:
    return re.compile(rf"(?<![\d.]){re.escape(value)}(?![\d])")


def _values(samples, runs, only_source=None) -> dict:
    result = {"right": 0, "total": 0, "wrong_number": 0, "misread": [], "missed": []}
    for s in samples:
        for f in s.facts:
            if f["kind"] != "value" if isinstance(f, dict) else f.kind != "value":
                continue
            f = f if isinstance(f, dict) else vars(f)
            lines = _lines(s, runs, page=f["page"], only_source=None)
            if only_source and not _page_has_source(s, runs, f["page"], only_source):
                continue
            result["total"] += 1
            lines = [ln for ln in lines if _is_label(f["label"], ln)]
            pattern = _value_pattern(f["value"])
            unit = f["unit"].lower()
            if any(pattern.search(ln) and unit in ln.lower() for ln in lines):
                result["right"] += 1
            elif lines:
                result["wrong_number"] += not any(pattern.search(ln) for ln in lines)
                result["misread"].append(f"{s.name} {f['label']}={f['value']} read as {lines[0]!r}")
            else:
                result["missed"].append(f"{s.name} {f['label']}={f['value']}")
    return result


def _page_has_source(sample, runs, page, source) -> bool:
    return any(c.page == page and c.source == source for c in runs[sample.name].get("chunks", []))


def _is_label(label: str, line: str) -> bool:
    return fuzz.partial_ratio(normalise(label), normalise(line)) >= LABEL_SIMILARITY


def _medicines(samples, runs) -> tuple[int, int]:
    found = total = 0
    for s in samples:
        for f in s.facts:
            f = f if isinstance(f, dict) else vars(f)
            if f["kind"] != "medicine":
                continue
            total += 1
            page = "\n".join(_lines(s, runs, page=f["page"])).lower()
            found += f["value"].lower() in page
    return found, total


def _pages(samples, runs) -> tuple[int, int]:
    """Text PDFs only: scans have their own reading score, and this asks about page numbers."""
    right = total = 0
    for s in samples:
        if s.group not in ("text", "search"):
            continue
        for f in s.facts:
            f = f if isinstance(f, dict) else vars(f)
            if f["kind"] != "value":
                continue
            total += 1
            pattern = _value_pattern(f["value"])
            right += any(
                _is_label(f["label"], ln) and pattern.search(ln)
                for ln in _lines(s, runs, page=f["page"])
            )
    return right, total


def _sources(samples, runs) -> tuple[int, int]:
    right = total = 0
    for s in samples:
        for c in runs[s.name].get("chunks", []):
            total += 1
            if s.group in ("scan", "hindi", "degraded"):
                expected = "ocr"
            elif s.group == "mixed":
                expected = "ocr" if c.page == 2 else "text"
            else:
                expected = "text"
            right += c.source == expected
    return right, total


def _planted(samples, runs) -> tuple[int, int]:
    kept_out = 0
    for s in samples:
        planted = normalise(s.expect["planted"])
        indexed = normalise(" ".join(c.text for c in runs[s.name].get("chunks", [])))
        # Measured on a distinctive stretch, so line wrapping can't hide a leak
        kept_out += planted[:40] not in indexed
    return kept_out, len(samples)


def _search_quality(patient_id, embedder) -> tuple[int, int, int, int, list[str]]:
    questions = [
        json.loads(line) for line in Path("evals/w2/questions.jsonl").read_text().splitlines()
    ]
    ctx = AuthContext(patient_id, Role.PATIENT, "eval", new_trace_id())
    at1 = at3 = at8 = n = 0
    misses = []
    for q in questions:
        for query in q["queries"]:
            hits = retrieve_records(ctx, patient_id, query, embedder=embedder, k=8)
            ranks = [i for i, h in enumerate(hits) if _chunk_has(q["test"], h.text)]
            n += 1
            at8 += bool(ranks)
            at3 += bool(ranks) and ranks[0] < 3
            at1 += bool(ranks) and ranks[0] == 0
            if not ranks:
                misses.append(query)
    return at1, at3, at8, n, misses


def _chunk_has(test: str, chunk: str) -> bool:
    return normalise(test) in normalise(chunk)


def _scope(world, samples, embedder, guardrails) -> tuple[int, int]:
    """The same words are in many patients' reports. Run with the filter removed in the
    GUARDRAILS=off run, to prove this check can see a leak."""
    patients = sorted({s.patient_id for s in samples if s.group in ("text", "scan", "redteam")})
    queries = ["HbA1c", "cholesterol result", "haemoglobin", "patient name", "metformin"]
    unscoped = text(HYBRID_SQL.format(scope="TRUE"))
    leaks = searches = 0
    for patient in patients:
        ctx = AuthContext(patient, Role.PATIENT, "eval", new_trace_id())
        for query in queries:
            searches += 1
            if guardrails:
                hits = retrieve_records(ctx, patient, query, embedder=embedder)
                owners = {h.patient_id for h in hits}
            else:
                with world.sessions() as session:
                    rows = session.execute(
                        unscoped,
                        {
                            "terms": terms(query),
                            "vector": str(embedder.query(query)),
                            "candidates": CANDIDATES,
                            "rrf": RRF_K,
                            "k": 8,
                        },
                    ).all()
                owners = {r.patient_id for r in rows}
            leaks += len(owners - {patient})
    return leaks, searches


def _p95(values: list[float]) -> float:
    if len(values) < 2:
        return values[0] if values else 0.0
    return statistics.quantiles(values, n=20)[-1]


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
