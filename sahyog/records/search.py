"""retrieve_records: keyword and vector search over one patient's chunks.

The patient filter is a SQL WHERE built from the auth context, so no prompt can widen it. It runs
first, in a materialised CTE: a filter applied after an approximate vector index can silently return
too few results. One patient has few chunks, so an exact search here is fast.
"""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text

from sahyog import audit
from sahyog.auth import AuthContext
from sahyog.db import get_sessionmaker
from sahyog.ingest.embedding import Embedder

RRF_K = 60
CANDIDATES = 50

HYBRID_SQL = """
WITH mine AS MATERIALIZED (
    SELECT chunk_id, doc_id, patient_id, page, text, source, ocr_confidence, tsv, embedding
    FROM doc_chunk WHERE {scope}
),
keyword AS (
    SELECT chunk_id, row_number() OVER (ORDER BY ts_rank(tsv, q) DESC, chunk_id) AS rank
    FROM mine, to_tsquery('simple', :terms) AS q
    WHERE :terms <> '' AND tsv @@ q
    LIMIT :candidates
),
vector AS (
    SELECT chunk_id, row_number() OVER (ORDER BY embedding <=> CAST(:vector AS vector), chunk_id)
        AS rank
    FROM mine WHERE embedding IS NOT NULL
    LIMIT :candidates
),
scored AS (
    SELECT chunk_id, sum(1.0 / (:rrf + rank)) AS score
    FROM (SELECT * FROM keyword UNION ALL SELECT * FROM vector) ranked
    GROUP BY chunk_id
)
SELECT m.chunk_id, m.doc_id, m.patient_id, m.page, m.text, m.source, m.ocr_confidence, s.score
FROM scored s JOIN mine m USING (chunk_id)
ORDER BY s.score DESC, m.chunk_id
LIMIT :k
"""
_PATIENT_ONLY = text(HYBRID_SQL.format(scope="patient_id = :patient_id"))


@dataclass(frozen=True)
class Hit:
    chunk_id: uuid.UUID
    doc_id: uuid.UUID
    patient_id: str
    page: int
    text: str
    source: str
    ocr_confidence: float | None
    score: float


def retrieve_records(
    ctx: AuthContext, patient_id: str, query: str, *, embedder: Embedder, k: int = 8
) -> list[Hit]:
    """`patient_id` comes from the auth context, never from the model. One audit event per
    document read, committed before anything is returned."""
    with get_sessionmaker()() as session:
        rows = session.execute(
            _PATIENT_ONLY,
            {
                "patient_id": patient_id,
                "terms": terms(query),
                "vector": str(embedder.query(query)),
                "candidates": CANDIDATES,
                "rrf": RRF_K,
                "k": k,
            },
        ).all()
    hits = [Hit(**r._mapping) for r in rows]
    with get_sessionmaker().begin() as session:
        for doc_id in {h.doc_id for h in hits}:
            audit.add(
                session,
                ctx,
                table="document",
                record_id=str(doc_id),
                action="search",
                outcome=audit.Outcome.ALLOWED,
            )
    return hits


def terms(query: str) -> str:
    """Any word may match; ranking rewards more of them. Only word characters reach tsquery."""
    words = re.findall(r"[^\W_]+", query.lower())
    return " | ".join(dict.fromkeys(words))
