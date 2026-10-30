"""W2 ingest endpoints. The patient comes from the token, never the request. A foreign job and a
missing job get the same reply, so job ids can't be probed."""

import json
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from sahyog import audit
from sahyog.api.idempotency import once
from sahyog.auth import AuthContext, Role, get_auth_context
from sahyog.db import get_session, get_sessionmaker
from sahyog.graphs import w1_messages
from sahyog.graphs.runtime import get_ask_graph
from sahyog.graphs.w2_ask import new_state
from sahyog.ingest.jobs import submit
from sahyog.ingest.parse import MAX_BYTES, Rejected
from sahyog.models import Document, IngestJob
from sahyog.safety.language import detect
from sahyog.scheduling import desk

log = logging.getLogger("sahyog.w2")
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


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    patient_id: str = Field(min_length=1, max_length=8)


@router.post("/ask")
def ask(body: AskIn, ctx: AuthContext = Depends(get_auth_context)):
    """Streams only after the safety check: text that might be blocked must never be shown. A failed
    consent check is a plain 403 with no data. An unexpected failure goes to a person."""
    state = new_state(ctx, body.patient_id, body.question)
    try:
        result = get_ask_graph().invoke(state)
    except Exception:  # noqa: BLE001 - this person may be describing an emergency
        log.exception("W2 ask failed, handing off (trace %s)", ctx.trace_id)
        result = _hand_off(ctx, state)
    if result.get("status") == "denied":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted to read these records")
    payload = {
        "ask_id": state["ask_id"],
        "status": result["status"],
        "answer": result["answer"],
        "citations": result.get("citations", []),
    }
    if result.get("sentences"):
        payload["sentences"] = result["sentences"]
    if result.get("scan_warning"):
        payload["scan_warning"] = result["scan_warning"]
    if result.get("ticket_id"):
        payload["ticket_id"] = result["ticket_id"]
    code = status.HTTP_200_OK
    if result.get("service_unavailable"):
        payload["handoff"] = True
        code = status.HTTP_503_SERVICE_UNAVAILABLE

    def events():
        yield f"event: answer\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", status_code=code)


def _hand_off(ctx: AuthContext, state: dict) -> dict:
    with get_sessionmaker().begin() as session:
        ticket = desk.open_ticket(
            session,
            kind="safety_unchecked",
            reason="Assistant failed answering this; not ruled out as an emergency",
            reason_codes=["run_failed"],
            patient_id=state["patient_id"] if ctx.role == Role.PATIENT else None,
            patient_text=state["question"],
            thread_id=state["ask_id"],
            trace_id=ctx.trace_id,
        )
    return {
        "status": "handed_to_desk",
        "answer": w1_messages.message("desk", detect(state["question"])),
        "ticket_id": str(ticket),
        "service_unavailable": True,
    }


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
