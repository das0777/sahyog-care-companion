"""Front-desk endpoints: the queue, booking overrides and ticket ownership (E2.2, E2.5)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from sahyog import audit
from sahyog.api.idempotency import once
from sahyog.auth import AuthContext, Role, get_auth_context
from sahyog.db import get_session, get_sessionmaker
from sahyog.models import Appointment, DeskTicket, Slot
from sahyog.scheduling import desk, service

router = APIRouter(prefix="/desk", tags=["desk"])

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=64)]


class TicketOut(BaseModel):
    ticket_id: uuid.UUID
    kind: str
    priority: int
    status: str
    reason: str
    reason_codes: list[str]
    owner: str | None
    patient_id: str | None
    appt_id: uuid.UUID | None
    slot_id: str | None
    patient_text: str | None
    created_at: datetime
    age_seconds: int


class OverrideIn(BaseModel):
    action: Literal["cancel", "move"]
    reason: str = Field(min_length=3, max_length=300)
    slot_id: str | None = Field(default=None, max_length=24)

    @model_validator(mode="after")
    def move_needs_a_block(self) -> "OverrideIn":
        if (self.action == "move") != (self.slot_id is not None):
            raise ValueError("slot_id is required for move and only for move")
        return self


def _desk_only(ctx: AuthContext, table: str, record_id: str, action: str) -> None:
    if ctx.role != Role.DESK:
        audit.record(
            ctx, table=table, record_id=record_id, action=action, outcome=audit.Outcome.DENIED
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Front desk only")


@router.get("/queue", response_model=list[TicketOut])
def read_queue(
    ctx: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
) -> list[TicketOut]:
    _desk_only(ctx, "desk_ticket", "queue", "read")
    tickets = desk.queue(session)
    session.commit()  # late-block tickets opened by the scan
    # One audit row per patient shown; the audit write happens before any data is returned
    with get_sessionmaker().begin() as audit_session:
        for t in tickets:
            audit.add(
                audit_session,
                ctx,
                table="desk_ticket",
                record_id=t.patient_id or str(t.ticket_id),
                action="read",
                outcome=audit.Outcome.ALLOWED,
            )
    now = datetime.now(UTC)
    return [
        TicketOut(
            ticket_id=t.ticket_id,
            kind=t.kind,
            priority=t.priority,
            status=t.status,
            reason=t.reason,
            reason_codes=t.reason_codes,
            owner=t.owner,
            patient_id=t.patient_id,
            appt_id=t.appt_id,
            slot_id=t.slot_id,
            patient_text=t.patient_text,
            created_at=t.created_at,
            age_seconds=int((now - t.created_at).total_seconds()),
        )
        for t in tickets
    ]


@router.post("/appointments/{appt_id}/override")
def override(
    appt_id: uuid.UUID,
    body: OverrideIn,
    idempotency_key: IdempotencyKey,
    ctx: AuthContext = Depends(get_auth_context),
):
    _desk_only(ctx, "appointment", str(appt_id), "override")

    def work():
        try:
            with get_sessionmaker().begin() as session:
                out = _apply_override(session, ctx, appt_id, body, idempotency_key)
                audit.add(
                    session,
                    ctx,
                    table="appointment",
                    record_id=str(appt_id),
                    action=f"override:{body.action}",
                    outcome=audit.Outcome.ALLOWED,
                )
                return 200, out
        except service.SlotNotFound as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment or block not found") from e
        except service.NotActive as e:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Appointment is {e}; it can't be changed"
            ) from e
        except (service.BlockFull, service.BlockStarted, service.AlreadyBooked) as e:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"{type(e).__name__}: that block can't take this booking"
            ) from e

    return once(ctx, idempotency_key, {"path": f"override:{appt_id}", **body.model_dump()}, work)


def _apply_override(session, ctx, appt_id, body: OverrideIn, key: str) -> dict:
    # Reserve before releasing, so a failed move leaves the patient's booking as it was
    appt = session.get(Appointment, appt_id)
    if appt is None:
        raise service.SlotNotFound(str(appt_id))
    if appt.status != "booked":
        raise service.NotActive(appt.status)
    out: dict = {"appt_id": str(appt_id), "action": body.action, "status": "cancelled"}
    new = None
    if body.action == "move":
        new = service.reserve_slot(
            session,
            slot_id=body.slot_id,
            patient_id=appt.patient_id,
            idem_key=f"desk:{uuid.uuid5(uuid.NAMESPACE_OID, ctx.actor_id + key)}",
            booked_by=ctx.actor_id,
        )
        out |= {
            "new_appt_id": str(new.appt_id),
            "token_no": new.token_no,
            "block_start": new.block_start.isoformat(),
            "block_end": new.block_end.isoformat(),
        }
    service.release_slot(session, appt_id)
    desk.close_for_appointment(session, appt_id, ctx.actor_id)
    if new:
        variables = {
            "token": new.token_no,
            "start": new.block_start.isoformat(),
            "end": new.block_end.isoformat(),
        }
        template = "booking_moved"
    else:
        slot = session.get(Slot, appt.slot_id)
        variables = {"start": slot.starts_at.isoformat(), "end": slot.ends_at.isoformat()}
        template = "booking_cancelled"
    desk.send_sms(
        session,
        patient_id=appt.patient_id,
        template=template,
        variables=variables,
        appt_id=new.appt_id if new else appt_id,
        trace_id=ctx.trace_id,
    )
    return out


@router.post("/tickets/{ticket_id}/{action}", response_model=TicketOut)
def update_ticket(
    ticket_id: uuid.UUID,
    action: Literal["claim", "close"],
    ctx: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
) -> TicketOut:
    _desk_only(ctx, "desk_ticket", str(ticket_id), action)
    # Replayable by nature: claiming or closing twice changes nothing further
    t = session.execute(
        select(DeskTicket).where(DeskTicket.ticket_id == ticket_id).with_for_update()
    ).scalar()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    if action == "claim" and t.owner not in (None, ctx.actor_id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Already claimed by {t.owner}")
    if t.status != "closed":
        t.owner = ctx.actor_id
        t.status = "claimed" if action == "claim" else "closed"
        if action == "close":
            t.closed_at = datetime.now(UTC)
    audit.add(
        session,
        ctx,
        table="desk_ticket",
        record_id=str(ticket_id),
        action=action,
        outcome=audit.Outcome.ALLOWED,
    )
    session.commit()
    now = datetime.now(UTC)
    return TicketOut(
        **{c: getattr(t, c) for c in TicketOut.model_fields if c != "age_seconds"},
        age_seconds=int((now - t.created_at).total_seconds()),
    )
