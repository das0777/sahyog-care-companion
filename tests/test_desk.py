import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from sahyog.auth import Role
from sahyog.db import get_sessionmaker
from sahyog.models import Appointment, AuditEvent, DeskTicket, Slot, SmsOutbox
from sahyog.scheduling import desk
from sahyog.scheduling.service import reserve_slot
from tests.conftest import bearer

DESK = bearer(Role.DESK, "DESK01")


def _key():
    return {"Idempotency-Key": uuid.uuid4().hex}


def _ticket(kind, age_minutes=0, **kw):
    with get_sessionmaker().begin() as s:
        tid = desk.open_ticket(
            s, kind=kind, reason=f"test {kind}", trace_id="t", thread_id=str(uuid.uuid4()), **kw
        )
        s.execute(
            update(DeskTicket)
            .where(DeskTicket.ticket_id == tid)
            .values(created_at=datetime.now(UTC) - timedelta(minutes=age_minutes))
        )
    return tid


def _booking(offset, patient="P0030"):
    with get_sessionmaker()() as s:
        slot = s.execute(select(Slot).order_by(Slot.slot_id).offset(offset).limit(1)).scalar()
    with get_sessionmaker().begin() as s:
        r = reserve_slot(
            s,
            slot_id=slot.slot_id,
            patient_id=patient,
            idem_key=uuid.uuid4().hex,
            booked_by="assistant",
        )
        desk.open_ticket(
            s,
            kind="ai_booking",
            reason="AI booked",
            trace_id="t",
            appt_id=r.appt_id,
            patient_id=patient,
        )
    return r


def test_queue_puts_red_flags_first_then_oldest_with_reason_owner_and_age(client):
    old = _ticket("low_confidence", age_minutes=50)
    newer = _ticket("advice_request", age_minutes=5)
    er = _ticket("er", age_minutes=1)
    unchecked = _ticket("safety_unchecked", age_minutes=2)
    rows = client.get("/desk/queue", headers=DESK).json()
    mine = [r["ticket_id"] for r in rows if r["ticket_id"] in map(str, (old, newer, er, unchecked))]
    assert mine == [str(unchecked), str(er), str(old), str(newer)]
    row = next(r for r in rows if r["ticket_id"] == str(old))
    assert row["reason"] and row["owner"] is None and row["age_seconds"] >= 50 * 60


def test_queue_is_desk_only_and_a_denied_read_is_audited(client):
    r = client.get("/desk/queue", headers=bearer(Role.PATIENT, "P0001"))
    assert r.status_code == 403
    with get_sessionmaker()() as s:
        assert s.execute(
            select(AuditEvent).where(
                AuditEvent.actor_id == "P0001",
                AuditEvent.table_name == "desk_ticket",
                AuditEvent.outcome == "denied",
            )
        ).first()


def test_claim_and_close_set_the_owner_and_closed_leaves_the_queue(client):
    tid = _ticket("low_confidence")
    assert client.post(f"/desk/tickets/{tid}/claim", headers=DESK).json()["owner"] == "DESK01"
    other = bearer(Role.DESK, "DESK02")
    assert client.post(f"/desk/tickets/{tid}/claim", headers=other).status_code == 409
    assert client.post(f"/desk/tickets/{tid}/close", headers=DESK).json()["status"] == "closed"
    assert str(tid) not in {r["ticket_id"] for r in client.get("/desk/queue", headers=DESK).json()}


def test_override_cancel_frees_the_place_writes_audit_and_sms_and_closes_the_ticket(client):
    r = _booking(30)
    res = client.post(
        f"/desk/appointments/{r.appt_id}/override",
        json={"action": "cancel", "reason": "patient rang to cancel"},
        headers=DESK | _key(),
    )
    assert res.status_code == 200 and res.json()["status"] == "cancelled"
    with get_sessionmaker()() as s:
        assert s.get(Appointment, r.appt_id).status == "cancelled"
        audit = (
            s.execute(select(AuditEvent).where(AuditEvent.record_id == str(r.appt_id)))
            .scalars()
            .one()
        )
        sms = s.execute(select(SmsOutbox).where(SmsOutbox.appt_id == r.appt_id)).scalars().one()
        t = s.execute(select(DeskTicket).where(DeskTicket.appt_id == r.appt_id)).scalars().one()
    assert audit.action == "override:cancel" and audit.actor_id == "DESK01"
    assert sms.template == "booking_cancelled"
    assert t.status == "closed" and t.owner == "DESK01"


def test_override_move_books_the_new_block_and_a_full_block_changes_nothing(client):
    r = _booking(31)
    with get_sessionmaker()() as s:
        target = s.execute(select(Slot).order_by(Slot.slot_id).offset(32).limit(1)).scalar()
    res = client.post(
        f"/desk/appointments/{r.appt_id}/override",
        json={"action": "move", "reason": "doctor on leave", "slot_id": target.slot_id},
        headers=DESK | _key(),
    )
    body = res.json()
    assert res.status_code == 200 and body["token_no"] >= 1
    with get_sessionmaker()() as s:
        assert s.get(Appointment, r.appt_id).status == "cancelled"
        new = s.get(Appointment, uuid.UUID(body["new_appt_id"]))
    assert new.slot_id == target.slot_id and new.booked_by == "DESK01"

    # Moving into a block the patient can't take leaves the booking as it was
    again = client.post(
        f"/desk/appointments/{new.appt_id}/override",
        json={"action": "move", "reason": "try again", "slot_id": "no-such-block"},
        headers=DESK | _key(),
    )
    assert again.status_code == 404
    with get_sessionmaker()() as s:
        assert s.get(Appointment, new.appt_id).status == "booked"


def test_override_needs_a_reason_the_desk_role_and_an_active_booking(client):
    r = _booking(33)
    url = f"/desk/appointments/{r.appt_id}/override"
    assert (
        client.post(url, json={"action": "cancel", "reason": ""}, headers=DESK | _key()).status_code
        == 422
    )
    body = {"action": "cancel", "reason": "not allowed"}
    patient = bearer(Role.PATIENT, "P0030") | _key()
    assert client.post(url, json=body, headers=patient).status_code == 403
    assert client.post(url, json=body, headers=DESK | _key()).status_code == 200
    # Already cancelled: a new key is a new request, and it is refused
    assert client.post(url, json=body, headers=DESK | _key()).status_code == 409
