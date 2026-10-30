"""What the screens need beyond the workflow APIs: lists of one's own things, and a development
sign-in. Each list is scoped by the token and audited, like every other read."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from sahyog import audit
from sahyog.auth import AuthContext, Role, get_auth_context, issue_token
from sahyog.config import get_settings
from sahyog.db import get_session
from sahyog.models import Appointment, Clinic, Doctor, Document, IngestJob, Patient, Slot

router = APIRouter(tags=["ui"])
LIST_LIMIT = 50


class LoginIn(BaseModel):
    role: Role
    actor_id: str = Field(min_length=1, max_length=16)


@router.post("/dev/login")
def dev_login(body: LoginIn) -> dict[str, str]:
    """Stands in for the hospital's OIDC. Off unless DEV_LOGIN is set: anyone can be anyone here."""
    if not get_settings().dev_login:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return {"token": issue_token(body.role, body.actor_id)}


def _only(ctx: AuthContext, role: Role, table: str) -> None:
    if ctx.role != role:
        audit.record(
            ctx, table=table, record_id=ctx.actor_id, action="list", outcome=audit.Outcome.DENIED
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted")


@router.get("/w1/appointments")
def my_appointments(
    ctx: AuthContext = Depends(get_auth_context), session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    _only(ctx, Role.PATIENT, "appointment")
    audit.record(
        ctx,
        table="appointment",
        record_id=ctx.actor_id,
        action="list",
        outcome=audit.Outcome.ALLOWED,
    )
    rows = session.execute(
        select(Appointment, Slot, Doctor.name, Clinic.name)
        .join(Slot, Appointment.slot_id == Slot.slot_id)
        .join(Doctor, Slot.doctor_id == Doctor.doctor_id)
        .join(Clinic, Slot.clinic_id == Clinic.clinic_id)
        .where(Appointment.patient_id == ctx.actor_id)
        .order_by(Slot.starts_at.desc())
        .limit(LIST_LIMIT)
    ).all()
    return [
        {
            "appt_id": str(a.appt_id),
            "status": a.status,
            "token_no": a.token_no,
            "doctor_name": doctor,
            "clinic": clinic,
            "block_start": s.starts_at.isoformat(),
            "block_end": s.ends_at.isoformat(),
        }
        for a, s, doctor, clinic in rows
    ]


@router.get("/w2/documents")
def my_documents(
    ctx: AuthContext = Depends(get_auth_context), session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    _only(ctx, Role.PATIENT, "document")
    audit.record(
        ctx, table="document", record_id=ctx.actor_id, action="list", outcome=audit.Outcome.ALLOWED
    )
    rows = session.execute(
        select(Document, IngestJob)
        .join(IngestJob, IngestJob.doc_id == Document.doc_id)
        .where(Document.patient_id == ctx.actor_id)
        .order_by(Document.uploaded_at.desc())
        .limit(LIST_LIMIT)
    ).all()
    return [
        {
            "doc_id": str(d.doc_id),
            "job_id": str(j.job_id),
            "status": d.status,
            "uploaded_at": d.uploaded_at.isoformat(),
            "pages_total": j.pages_total,
            "pages_ocr": j.pages_ocr,
            "chunks_indexed": j.chunks_indexed,
            "chunks_quarantined": j.chunks_quarantined,
            "reason": j.reason,
        }
        for d, j in rows
    ]


@router.get("/w3/appointments")
def doctor_appointments(
    ctx: AuthContext = Depends(get_auth_context), session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    _only(ctx, Role.DOCTOR, "appointment")
    rows = session.execute(
        select(Appointment, Slot, Patient.name)
        .join(Slot, Appointment.slot_id == Slot.slot_id)
        .join(Patient, Appointment.patient_id == Patient.patient_id)
        .where(Slot.doctor_id == ctx.actor_id, Appointment.status != "cancelled")
        .order_by(Slot.starts_at, Appointment.token_no)
        .limit(LIST_LIMIT)
    ).all()
    # One audit row per patient shown, before any data is returned
    for appointment, _, _ in rows:
        audit.record(
            ctx,
            table="patient",
            record_id=appointment.patient_id,
            action="list",
            outcome=audit.Outcome.ALLOWED,
        )
    return [
        {
            "appt_id": str(a.appt_id),
            "status": a.status,
            "token_no": a.token_no,
            "patient_name": name,
            "block_start": s.starts_at.isoformat(),
            "block_end": s.ends_at.isoformat(),
        }
        for a, s, name in rows
    ]
