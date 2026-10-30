"""`make eval-live set=...`: W3 on a real model. Costs money, and each run prints how much.

scribe-tune    The dev dictations. The only set prompts may be tuned against.
scribe-freeze  Record the prompts' hash, ready to commit and tag.
scribe         The test dictations. Once.
scribe-speed   Draft time after the transcript.
scribe-audio   Speech to text on the synthetic audio. No outside model.
"""

import argparse
import json
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from sahyog.config import get_settings
from sahyog.db import get_sessionmaker
from sahyog.graphs import w3_prompts as prompts
from sahyog.graphs.w3 import ScribeDeps, build_w3
from sahyog.llm.gateway import build_gateway
from sahyog.models import Patient, Slot
from sahyog.safety.text import normalise
from sahyog.scribe.grounding import KNOWN_MOLECULES
from sahyog.scribe.stock import CsvStockAdapter

W3 = Path("evals/w3")
FROZEN = W3 / "frozen.json"
MEASUREMENTS = W3 / "measurements.jsonl"
PATIENT = "P0997"
AUDIO_KEYWORDS = {
    "dictation-1.m4a": [
        "knee",
        "stairs",
        "swelling",
        "osteoarthritis",
        "diclofenac",
        "physiotherapy",
    ],
    "dictation-2.m4a": ["diabetic", "statin", "metformin", "500", "three months"],
    "dictation-3.m4a": ["पेट", "दर्द", "40"],
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sahyog.evals.w3_live")
    parser.add_argument(
        "--set",
        required=True,
        choices=[
            "scribe-tune",
            "scribe-freeze",
            "scribe",
            "scribe-ext",
            "scribe-speed",
            "scribe-audio",
        ],
    )
    args = parser.parse_args(argv)
    if args.set == "scribe-audio":
        return _audio()
    settings = get_settings()
    if not settings.has_real_model:
        sys.exit("Needs a real model. Run `make key-from-clipboard` yourself, then run this again.")
    if args.set == "scribe-freeze":
        FROZEN.write_text(
            json.dumps(
                {
                    "prompts_hash": prompts.PROMPTS_HASH,
                    "small_model": settings.outside_models[0],
                    "large_model": settings.outside_models[1],
                    "frozen_on": _today(),
                },
                indent=2,
            )
            + "\n"
        )
        print(f"Frozen at {prompts.PROMPTS_HASH}. Commit it and tag s5-prompts-frozen.")
        return 0
    if args.set in ("scribe", "scribe-ext"):
        _guard(args.set)
    gateway = build_gateway(settings)
    cases = [json.loads(ln) for ln in (W3 / "golden.jsonl").read_text().splitlines()]
    if args.set == "scribe-speed":
        code = _speed(gateway, cases)
    else:
        split = {"scribe-tune": "dev", "scribe": "test", "scribe-ext": "ext"}[args.set]
        record = args.set if args.set != "scribe-tune" else None
        code = _quality(gateway, [c for c in cases if c["split"] == split], record)
    spent = sum(r.cost_usd for r in gateway.records)
    print(f"\nCost of this run: ${spent:.4f} over {len(gateway.records)} model calls")
    return code


def _guard(name: str) -> None:
    if not FROZEN.exists():
        sys.exit("Prompts aren't frozen yet.")
    if json.loads(FROZEN.read_text())["prompts_hash"] != prompts.PROMPTS_HASH:
        sys.exit("Prompts changed since the freeze.")
    for line in MEASUREMENTS.read_text().splitlines() if MEASUREMENTS.exists() else []:
        done = json.loads(line)
        if done["set"] == name and done["prompts_hash"] == prompts.PROMPTS_HASH:
            sys.exit(f"Already measured on these prompts: {done['summary']}.")


def _draft(gateway, case) -> dict:
    sessions = get_sessionmaker()
    with sessions() as session:
        slot = session.execute(select(Slot).limit(1)).scalar()
        patient = session.get(Patient, PATIENT)
    graph = build_w3(
        ScribeDeps(gateway, CsvStockAdapter(Path(get_settings().stock_csv)), sessions),
        InMemorySaver(),
    )
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    started = time.perf_counter()
    graph.invoke(
        {
            "thread_id": "eval",
            "encounter_id": str(uuid.uuid4()),
            "doctor_id": slot.doctor_id,
            "patient_id": patient.patient_id,
            "clinic_id": slot.clinic_id,
            "trace_id": uuid.uuid4().hex,
            "transcript": case["transcript"],
        },
        config,
    )
    seconds = time.perf_counter() - started
    pauses = [i.value for t in graph.get_state(config).tasks for i in t.interrupts]
    return {"case": case, "seconds": seconds, "draft": pauses[0] if pauses else None}


def _quality(gateway, cases, record: str | None) -> int:
    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(lambda c: _draft(gateway, c), cases))
    failed = [r for r in rows if r["draft"] is None]
    done = [r for r in rows if r["draft"]]
    term_hit = term_total = 0
    missed_terms = []
    section = {"S": "subjective", "O": "objective", "A": "assessment", "P": "plan"}
    for r in done:
        for key, terms in r["case"]["expect"]["soap"].items():
            text = normalise(" ".join(ln["text"] for ln in r["draft"]["soap"][section[key]]))
            for term in terms:
                term_total += 1
                if normalise(term) in text:
                    term_hit += 1
                else:
                    missed_terms.append(f"{r['case']['id']} {key}: {term}")
    invented = []
    tp = fp = fn = 0
    wrong = []
    gap_hit = gap_total = 0
    flagged = total_meds = 0
    for r in done:
        transcript = normalise(r["case"]["transcript"])
        expect = r["case"]["expect"]
        got = r["draft"]["medicines"]
        names = {normalise(m["name"]) for m in got}
        wanted = {normalise(m["name"]) for m in expect["medicines"]}
        for name in names:
            if not any(w in name or name in w for w in wanted):
                fp += 1
                wrong.append(f"{r['case']['id']} extra: {name}")
            else:
                tp += 1
        for w in wanted:
            if not any(w in n or n in w for n in names):
                fn += 1
                wrong.append(f"{r['case']['id']} missed: {w}")
        plan = normalise(" ".join(ln["text"] for ln in r["draft"]["soap"]["plan"]))
        for word in KNOWN_MOLECULES:
            if (word in plan or word in " ".join(names)) and word not in transcript:
                invented.append(f"{r['case']['id']}: {word}")
        gaps = " ".join(normalise(g["term"]) for g in r["draft"]["gaps"])
        for g in expect["gaps"]:
            gap_total += 1
            if normalise(g) in gaps:
                gap_hit += 1
            else:
                wrong.append(f"{r['case']['id']} no gap for: {g}")
        total_meds += len(got)
        flagged += sum(bool(m.get("stock")) and "age_days" in m["stock"] for m in got)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    term_rate = term_hit / term_total if term_total else 0.0
    gates = [
        ("G2", "Drafts valid, A and P grounded", "100%", f"{len(done)}/{len(rows)}", not failed),
        ("G3", "Invented molecules", "0", str(len(invented)), not invented),
        (
            "G4",
            "Class without molecule stays a gap",
            "100%",
            f"{gap_hit}/{gap_total}",
            gap_hit == gap_total,
        ),
        (
            "G5",
            "SOAP terms found in the right field",
            "≥ 85%",
            f"{term_hit}/{term_total} ({term_rate:.0%})",
            term_rate >= 0.85,
        ),
        (
            "G6",
            "Medicine precision",
            "100%",
            f"{precision:.0%} ({tp} right, {fp} extra)",
            precision == 1.0,
        ),
        ("G6r", "Medicine recall", "reported", f"{recall:.0%} ({fn} missed)", None),
        (
            "G9",
            "Medicines with a stock line and age",
            "100%",
            f"{flagged}/{total_meds}",
            flagged == total_meds,
        ),
    ]
    print()
    ok = True
    for cid, name, target, result, passed in gates:
        ok = ok and passed is not False
        status = {True: "PASS", False: "FAIL", None: "info"}[passed]
        print(f"{cid:<4} {name:<38} {target:<9} {status:<5} {result}")
    for line in invented + wrong + missed_terms:
        print(f"  {line}")
    flags = [f for r in done for f in r["draft"]["flags"]]
    print(f"     Grounding flags raised: {len(flags)}; {flags[:4]}")
    print(f"     Drafts: median {statistics.median(r['seconds'] for r in done):.1f} s")
    if record:
        summary = "; ".join(f"{c} {res}" for c, _, _, res, _ in gates)
        with MEASUREMENTS.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "set": record,
                        "date": _today(),
                        "prompts_hash": prompts.PROMPTS_HASH,
                        "summary": summary,
                        "misses": invented + wrong + missed_terms,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return 0 if ok else 1


def _speed(gateway, cases) -> int:
    times = [_draft(gateway, cases[i % len(cases)])["seconds"] for i in range(24)]
    p95 = statistics.quantiles(times, n=20)[-1]
    print(
        f"\nG1 Draft after transcript ({len(times)} runs, one at a time): median "
        f"{statistics.median(times):.1f} s, p95 {p95:.1f} s, slowest {max(times):.1f} s "
        "(target p95 < 20 s)"
    )
    print(f"{'PASS' if p95 < 20 else 'FAIL'}. Not a load test; that is S7.")
    return 0 if p95 < 20 else 1


def _audio() -> int:
    from sahyog.scribe.transcribe import transcribe

    found = total = 0
    for name, words in AUDIO_KEYWORDS.items():
        started = time.perf_counter()
        text = transcribe(W3 / "audio" / name)
        seconds = time.perf_counter() - started
        hits = [w for w in words if w in text.lower()]
        found += len(hits)
        total += len(words)
        print(f"{name}: {len(hits)}/{len(words)} words, {seconds:.1f} s\n  {text[:220]}")
    print(f"\nG13 Key words heard: {found}/{total}. Synthetic voices.")
    return 0


def _today() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).date().isoformat()


if __name__ == "__main__":
    sys.exit(main())
