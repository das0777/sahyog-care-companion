"""W2 ingest: a PDF to patient-tagged chunks. Runs on the worker, one document at a time.

load → parse → identity_check → chunk → injection_scan → embed → index. Identity comes from the job
row, which the API wrote from the token, never from the file. Calls no outside model.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from sahyog.config import get_settings
from sahyog.ingest import chunk as chunking
from sahyog.ingest import identity, parse, scan
from sahyog.ingest.embedding import Embedder, content_hash
from sahyog.models import (
    DocChunk,
    Document,
    EmbeddingCache,
    IngestJob,
    Patient,
    QuarantinedChunk,
)
from sahyog.scheduling import desk
from sahyog.storage import get_minio

log = logging.getLogger("sahyog.ingest")


class IngestState(TypedDict, total=False):
    job_id: str
    doc_id: str
    patient_id: str
    trace_id: str
    data: bytes
    pages: list[parse.PageText]
    chunks: list[chunking.Chunk]
    quarantined: list[tuple[chunking.Chunk, str]]
    vectors: list[list[float]]
    outcome: str
    reason: str | None


@dataclass
class IngestDeps:
    embedder: Embedder
    sessions: sessionmaker[Session]
    scan_enabled: bool = True  # off only for the GUARDRAILS=off eval run


def build_ingest(deps: IngestDeps):
    n = _Nodes(deps)
    g = StateGraph(IngestState)
    for name in ("load", "parse", "identity_check", "chunk", "injection_scan", "embed", "index"):
        g.add_node(name, getattr(n, name))
    g.add_node("hold", n.hold)
    g.add_edge(START, "load")
    g.add_edge("load", "parse")
    g.add_edge("parse", "identity_check")
    g.add_conditional_edges(
        "identity_check", lambda s: "hold" if s.get("outcome") == "held" else "chunk"
    )
    g.add_edge("chunk", "injection_scan")
    g.add_edge("injection_scan", "embed")
    g.add_edge("embed", "index")
    g.add_edge("index", END)
    g.add_edge("hold", END)
    return g.compile()


class _Nodes:
    def __init__(self, deps: IngestDeps):
        self.d = deps

    def load(self, state: IngestState) -> IngestState:
        with self.d.sessions() as session:
            uri = session.scalar(
                select(Document.uri).where(Document.doc_id == uuid.UUID(state["doc_id"]))
            )
        response = get_minio().get_object(get_settings().report_bucket, uri)
        try:
            return {"data": response.read()}
        finally:
            response.close()
            response.release_conn()

    def parse(self, state: IngestState) -> IngestState:
        parse.check_pdf(state["data"])
        pages = parse.read_pages(state["data"])
        if not any(p.text.strip() for p in pages):
            raise parse.Rejected("No readable text was found in this PDF.")
        with self.d.sessions.begin() as session:
            session.execute(
                update(Document)
                .where(Document.doc_id == uuid.UUID(state["doc_id"]))
                .values(status="parsed")
            )
            session.execute(
                update(IngestJob)
                .where(IngestJob.job_id == uuid.UUID(state["job_id"]))
                .values(
                    pages_total=len(pages),
                    pages_ocr=sum(p.source == "ocr" for p in pages),
                )
            )
        return {"pages": pages}

    def identity_check(self, state: IngestState) -> IngestState:
        with self.d.sessions() as session:
            patient = session.get(Patient, state["patient_id"])
            why = identity.mismatch(state["pages"], name=patient.name, abha_id=patient.abha_id)
        return {"outcome": "held", "reason": why} if why else {}

    def hold(self, state: IngestState) -> IngestState:
        with self.d.sessions.begin() as session:
            _finish(session, state, "held", state["reason"])
            desk.open_ticket(
                session,
                kind="doc_held",
                reason=f"Report held: {state['reason']}",
                reason_codes=["wrong_patient"],
                patient_id=state["patient_id"],
                thread_id=state["doc_id"],
                trace_id=state["trace_id"],
            )
        return {}

    def chunk(self, state: IngestState) -> IngestState:
        return {"chunks": chunking.chunk_pages(state["pages"])}

    def injection_scan(self, state: IngestState) -> IngestState:
        keep, quarantined = [], []
        for c in state["chunks"]:
            why = scan.flags_injection(c.text) if self.d.scan_enabled else None
            if why:
                quarantined.append((c, why))
            else:
                keep.append(c)
        return {"chunks": keep, "quarantined": quarantined}

    def embed(self, state: IngestState) -> IngestState:
        """Cached by content hash, so a re-uploaded report isn't embedded twice."""
        texts = [c.text for c in state["chunks"]]
        hashes = [content_hash(t) for t in texts]
        model = self.d.embedder.model
        with self.d.sessions() as session:
            cached = dict(
                session.execute(
                    select(EmbeddingCache.content_hash, EmbeddingCache.embedding).where(
                        EmbeddingCache.model == model, EmbeddingCache.content_hash.in_(hashes)
                    )
                ).all()
            )
        missing = [
            (h, t) for h, t in dict(zip(hashes, texts, strict=True)).items() if h not in cached
        ]
        if missing:
            vectors = self.d.embedder.passages([t for _, t in missing])
            fresh = {h: v for (h, _), v in zip(missing, vectors, strict=True)}
            with self.d.sessions.begin() as session:
                session.execute(
                    insert(EmbeddingCache)
                    .values(
                        [
                            {"content_hash": h, "model": model, "embedding": v}
                            for h, v in fresh.items()
                        ]
                    )
                    .on_conflict_do_nothing()
                )
            cached |= fresh
        return {"vectors": [list(cached[h]) for h in hashes]}

    def index(self, state: IngestState) -> IngestState:
        """One transaction: a retry replaces the document's chunks and can't duplicate them."""
        doc_id = uuid.UUID(state["doc_id"])
        with self.d.sessions.begin() as session:
            session.execute(delete(DocChunk).where(DocChunk.doc_id == doc_id))
            session.execute(delete(QuarantinedChunk).where(QuarantinedChunk.doc_id == doc_id))
            for c, v in zip(state["chunks"], state["vectors"], strict=True):
                session.add(
                    DocChunk(
                        doc_id=doc_id,
                        patient_id=state["patient_id"],
                        page=c.page,
                        text=c.text,
                        embedding=v,
                        source=c.source,
                        ocr_confidence=c.confidence,
                    )
                )
            for c, why in state["quarantined"]:
                session.add(
                    QuarantinedChunk(
                        doc_id=doc_id,
                        patient_id=state["patient_id"],
                        page=c.page,
                        text=c.text,
                        reason=why,
                    )
                )
            if state["quarantined"]:
                desk.open_ticket(
                    session,
                    kind="doc_quarantine",
                    reason=f"{len(state['quarantined'])} part(s) of a report quarantined for "
                    "instruction-like text",
                    reason_codes=["prompt_injection"],
                    patient_id=state["patient_id"],
                    thread_id=state["doc_id"],
                    trace_id=state["trace_id"],
                )
            _finish(
                session,
                state,
                "indexed",
                None,
                chunks=len(state["chunks"]),
                quarantined=len(state["quarantined"]),
            )
        return {}


def _finish(session, state, status, reason, *, chunks=0, quarantined=0) -> None:
    session.execute(
        update(Document).where(Document.doc_id == uuid.UUID(state["doc_id"])).values(status=status)
    )
    session.execute(
        update(IngestJob)
        .where(IngestJob.job_id == uuid.UUID(state["job_id"]))
        .values(
            status="done",
            reason=reason,
            chunks_indexed=chunks,
            chunks_quarantined=quarantined,
            finished_at=datetime.now(UTC),
            lease_until=None,
        )
    )


def fail_job(sessions, job_id: uuid.UUID, doc_id: uuid.UUID, reason: str) -> None:
    with sessions.begin() as session:
        session.execute(update(Document).where(Document.doc_id == doc_id).values(status="failed"))
        session.execute(
            update(IngestJob)
            .where(IngestJob.job_id == job_id)
            .values(status="failed", reason=reason, finished_at=datetime.now(UTC), lease_until=None)
        )
