"""W2 ingest endpoints. The patient comes from the token, never the request. A foreign job and a
missing job get the same reply, so job ids can't be probed."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from sahyog import audit
from sahyog.api.idempotency import once
from sahyog.auth import AuthContext, Role, get_auth_context
from sahyog.db import get_session, get_sessionmaker
from sahyog.ingest.jobs import submit
from sahyog.ingest.parse import MAX_BYTES, Rejected
from sahyog.models import Document, IngestJob

router = APIRouter(prefix="/w2", tags=["w2"])

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=64)]


@router.post("/documents", status_code=status.HTTP_202_ACCEPTED)
async def upload(
    idempotency_key: IdempotencyKey,
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    if ctx.role != Role.PATIENT:
        # Caregivers wait for consent enforcement in S4: refused rather than allowed unchecked
        audit.record(
            ctx,
            table="document",
            record_id=ctx.actor_id,
            action="upload",
            outcome=audit.Outcome.DENIED,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the patient can upload for now")
    data = await file.read(MAX_BYTES + 1)
    return await run_in_threadpool(_store, ctx, idempotency_key, data)


def _store(ctx: AuthContext, key: str, data: bytes):
    import hashlib

    def work() -> tuple[int, dict[str, Any]]:
        try:
            result = submit(
                get_sessionmaker(), data=data, patient_id=ctx.actor_id, trace_id=ctx.trace_id
            )
        except Rejected as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
        audit.record(
            ctx,
            table="document",
            record_id=str(result.doc_id),
            action="upload",
            outcome=audit.Outcome.ALLOWED,
        )
        return 202, {
            "job_id": str(result.job_id),
            "doc_id": str(result.doc_id),
            "duplicate": result.duplicate,
        }

    return once(ctx, key, {"path": "upload", "sha256": hashlib.sha256(data).hexdigest()}, work)


@router.get("/documents/{job_id}")
def job_status(
    job_id: uuid.UUID,
    ctx: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    row = session.execute(
        select(IngestJob, Document.status)
        .join(Document, IngestJob.doc_id == Document.doc_id)
        .where(IngestJob.job_id == job_id)
    ).first()
    allowed = row is not None and ctx.role == Role.PATIENT and row[0].patient_id == ctx.actor_id
    audit.record(
        ctx,
        table="ingest_job",
        record_id=str(job_id),
        action="read",
        outcome=audit.Outcome.ALLOWED if allowed else audit.Outcome.DENIED,
    )
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such upload")
    job, doc_status = row
    return {
        "job_id": str(job.job_id),
        "doc_id": str(job.doc_id),
        "status": doc_status,
        "pages_total": job.pages_total,
        "pages_ocr": job.pages_ocr,
        "chunks_indexed": job.chunks_indexed,
        "chunks_quarantined": job.chunks_quarantined,
        "reason": job.reason,
    }
