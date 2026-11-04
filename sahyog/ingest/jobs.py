"""Submit a report and run its job. Postgres is the queue, so the document and its job commit
together, and `FOR UPDATE SKIP LOCKED` lets a bounded pool of workers share it."""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sahyog.config import get_settings
from sahyog.graphs.w2_ingest import fail_job
from sahyog.ingest.parse import Rejected, check_pdf, pdf_stream
from sahyog.models import Document, IngestJob
from sahyog.storage import get_minio

log = logging.getLogger("sahyog.ingest")

MAX_ATTEMPTS = 3
RETRY_REASON = "We couldn't process this file. Please try again, or ask the front desk for help."

_CLAIM = text(
    """
    UPDATE ingest_job SET
        status = 'running',
        attempts = attempts + 1,
        started_at = coalesce(started_at, now()),
        lease_until = :lease_until
    WHERE job_id = (
        SELECT job_id FROM ingest_job
        WHERE (status = 'queued' OR (status = 'running' AND lease_until < now()))
          AND attempts < :max_attempts
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING job_id, doc_id, patient_id, trace_id
    """
)
_GIVE_UP = text(
    """
    UPDATE ingest_job SET status = 'failed', reason = :reason, finished_at = now(),
        lease_until = NULL
    WHERE status = 'running' AND lease_until < now() AND attempts >= :max_attempts
    RETURNING doc_id
    """
)


@dataclass(frozen=True)
class Submitted:
    job_id: uuid.UUID
    doc_id: uuid.UUID
    duplicate: bool = False


def submit(
    session_factory,
    *,
    data: bytes,
    patient_id: str,
    trace_id: str,
    doc_type: str = "report",
    run_here: bool = False,
) -> Submitted:
    """Store the file and queue its job. Raises Rejected for a file that can never be read.
    `run_here` claims the job for the caller, so a running worker leaves it alone (evals, tests)."""
    check_pdf(data)
    digest = hashlib.sha256(data).hexdigest()
    existing = _existing(session_factory, patient_id, digest)
    if existing:
        return existing
    doc_id, job_id = uuid.uuid4(), uuid.uuid4()
    uri = f"patients/{patient_id}/{doc_id}.pdf"
    get_minio().put_object(
        get_settings().report_bucket,
        uri,
        pdf_stream(data),
        len(data),
        content_type="application/pdf",
    )
    try:
        with session_factory.begin() as session:
            session.add(
                Document(
                    doc_id=doc_id,
                    patient_id=patient_id,
                    type=doc_type,
                    uri=uri,
                    content_hash=digest,
                )
            )
            session.flush()
            claimed = (
                {
                    "status": "running",
                    "attempts": 1,
                    "lease_until": datetime.now(UTC) + timedelta(hours=1),
                }
                if run_here
                else {}
            )
            session.add(
                IngestJob(
                    job_id=job_id,
                    doc_id=doc_id,
                    patient_id=patient_id,
                    trace_id=trace_id,
                    **claimed,
                )
            )
    except IntegrityError:
        # The same file, uploaded at the same moment: the first one won
        get_minio().remove_object(get_settings().report_bucket, uri)
        found = _existing(session_factory, patient_id, digest)
        if found:
            return found
        raise
    return Submitted(job_id, doc_id)


def _existing(session_factory, patient_id: str, digest: str) -> Submitted | None:
    with session_factory() as session:
        row = session.execute(
            select(IngestJob.job_id, Document.doc_id)
            .join(Document, IngestJob.doc_id == Document.doc_id)
            .where(
                Document.patient_id == patient_id,
                Document.content_hash == digest,
                Document.status != "failed",
            )
        ).first()
    return Submitted(row[0], row[1], True) if row else None


def claim(session: Session, *, lease_s: int) -> dict | None:
    row = session.execute(
        _CLAIM,
        {
            "lease_until": datetime.now(UTC) + timedelta(seconds=lease_s),
            "max_attempts": MAX_ATTEMPTS,
        },
    ).first()
    return dict(row._mapping) if row else None


def give_up_on_expired(sessions) -> int:
    """A job whose worker died on its last attempt never finishes on its own."""
    with sessions.begin() as session:
        docs = session.execute(
            _GIVE_UP, {"reason": RETRY_REASON, "max_attempts": MAX_ATTEMPTS}
        ).all()
        for (doc_id,) in docs:
            session.execute(
                update(Document).where(Document.doc_id == doc_id).values(status="failed")
            )
    return len(docs)


def run_job(graph, sessions, job: dict) -> None:
    """One attempt. A Rejected file fails for good; anything else may be retried by the lease."""
    state = {
        "job_id": str(job["job_id"]),
        "doc_id": str(job["doc_id"]),
        "patient_id": job["patient_id"],
        "trace_id": job["trace_id"],
    }
    try:
        graph.invoke(state)
    except Rejected as e:
        fail_job(sessions, job["job_id"], job["doc_id"], str(e))
    except Exception:  # noqa: BLE001 - one bad file must never take the worker down
        log.exception("ingest failed for job %s", job["job_id"])
        with sessions.begin() as session:
            attempts = session.scalar(
                select(IngestJob.attempts).where(IngestJob.job_id == job["job_id"])
            )
            if attempts < MAX_ATTEMPTS:
                session.execute(
                    update(IngestJob)
                    .where(IngestJob.job_id == job["job_id"])
                    .values(status="queued", lease_until=None)
                )
                return
        fail_job(sessions, job["job_id"], job["doc_id"], RETRY_REASON)
