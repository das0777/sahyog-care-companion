"""The front-desk side of W1: tickets, the queue order, late blocks and the SMS stub."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from sahyog.models import Appointment, DeskTicket, Slot, SmsOutbox

LATE_AFTER = timedelta(minutes=30)  # E2.5

# 0 goes first. A safety check that did not run is treated like a red flag: nobody has ruled out
# an emergency yet.
PRIORITY = {"er": 0, "safety_unchecked": 0}
DEFAULT_PRIORITY = 1

SMS_TEMPLATES = {"booking_confirmed", "booking_cancelled", "booking_moved"}


def open_ticket(
    session: Session,
    *,
    kind: str,
    reason: str,
    trace_id: str,
    reason_codes: list[str] | None = None,
    patient_id: str | None = None,
    patient_text: str | None = None,
    appt_id: uuid.UUID | None = None,
    slot_id: str | None = None,
    thread_id: str | None = None,
) -> uuid.UUID:
    """Open a ticket, or return the one already open for this thread, appointment or block."""
    values = {
        "kind": kind,
        "priority": PRIORITY.get(kind, DEFAULT_PRIORITY),
        "reason": reason,
        "reason_codes": reason_codes or [],
        "patient_id": patient_id,
        "patient_text": patient_text,
        "appt_id": appt_id,
        "slot_id": slot_id,
        "thread_id": thread_id,
        "trace_id": trace_id,
    }
    ticket_id = session.scalar(
        insert(DeskTicket).values(values).on_conflict_do_nothing().returning(DeskTicket.ticket_id)
    )
    if ticket_id:
        return ticket_id
    existing = select(DeskTicket.ticket_id).where(DeskTicket.kind == kind)
    if appt_id:
        existing = existing.where(DeskTicket.appt_id == appt_id)
    elif thread_id:
        existing = existing.where(DeskTicket.thread_id == thread_id)
    else:
        existing = existing.where(DeskTicket.slot_id == slot_id)
    return session.scalar(existing)


def queue(session: Session, *, now: datetime | None = None) -> list[DeskTicket]:
    """Open work: red flags first, then oldest first (E2.5). Late blocks are checked on each read
    because there is no scheduler yet."""
    scan_late_blocks(session, now=now)
    return list(
        session.execute(
            select(DeskTicket)
            .where(DeskTicket.status != "closed")
            .order_by(DeskTicket.priority, DeskTicket.created_at, DeskTicket.ticket_id)
        ).scalars()
    )


def scan_late_blocks(session: Session, *, now: datetime | None = None) -> int:
    """One ticket per block that ended more than 30 minutes ago with patients still waiting."""
    now = now or datetime.now(UTC)
    waiting = session.execute(
        select(Slot.slot_id, Slot.starts_at, func.count())
        .join(Appointment, Appointment.slot_id == Slot.slot_id)
        .where(Slot.ends_at < now - LATE_AFTER, Appointment.status.in_(("booked", "checked_in")))
        .group_by(Slot.slot_id)
    ).all()
    for slot_id, _, n in waiting:
        open_ticket(
            session,
            kind="late_block",
            reason=f"Block {slot_id} is over 30 minutes late with {n} patient(s) still waiting",
            reason_codes=["late_block"],
            slot_id=slot_id,
            trace_id="late-block-scan",
        )
    return len(waiting)


def send_sms(
    session: Session,
    *,
    patient_id: str,
    template: str,
    variables: dict,
    trace_id: str,
    appt_id: uuid.UUID | None = None,
) -> None:
    """Templates only, never free text. A stub: the row is the whole effect."""
    if template not in SMS_TEMPLATES:
        raise ValueError(f"unknown SMS template {template}")
    session.add(
        SmsOutbox(
            patient_id=patient_id,
            template=template,
            vars=variables,
            appt_id=appt_id,
            trace_id=trace_id,
        )
    )


def close_for_appointment(session: Session, appt_id: uuid.UUID, owner: str) -> None:
    session.execute(
        update(DeskTicket)
        .where(DeskTicket.appt_id == appt_id, DeskTicket.status != "closed")
        .values(status="closed", owner=owner, closed_at=datetime.now(UTC))
    )
