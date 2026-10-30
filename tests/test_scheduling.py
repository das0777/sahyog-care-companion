from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from sahyog.db import get_sessionmaker
from sahyog.models import Appointment, DeskTicket, Slot
from sahyog.scheduling import desk, service
from sahyog.scheduling.service import (
    AlreadyBooked,
    BlockFull,
    BlockStarted,
    IdempotencyConflict,
    SlotNotFound,
    reserve_slot,
)


def _slots(offset: int, n: int = 1) -> list[Slot]:
    with get_sessionmaker()() as s:
        return list(
            s.execute(select(Slot).order_by(Slot.slot_id).offset(offset).limit(n)).scalars()
        )


def _book(slot_id, patient, key):
    with get_sessionmaker().begin() as s:
        return reserve_slot(s, slot_id=slot_id, patient_id=patient, idem_key=key, booked_by="test")


def _active(slot_id) -> list[Appointment]:
    with get_sessionmaker()() as s:
        return list(
            s.execute(
                select(Appointment).where(
                    Appointment.slot_id == slot_id, Appointment.status != "cancelled"
                )
            ).scalars()
        )


def test_no_double_booking_under_50_concurrent_patients():
    slot = _slots(10)[0]

    def attempt(i):
        try:
            return _book(slot.slot_id, f"P{i + 1:04d}", f"concurrent-{i}").token_no
        except BlockFull:
            return None

    with ThreadPoolExecutor(50) as pool:
        tokens = [t for t in pool.map(attempt, range(50)) if t]
    assert sorted(tokens) == list(range(1, slot.capacity + 1))
    assert len(_active(slot.slot_id)) == slot.capacity


def test_same_key_20_concurrent_retries_make_one_appointment():
    slot = _slots(11)[0]
    with ThreadPoolExecutor(20) as pool:
        out = list(pool.map(lambda _: _book(slot.slot_id, "P0001", "retry-key"), range(20)))
    assert len({r.appt_id for r in out}) == 1
    assert len(_active(slot.slot_id)) == 1


def test_same_key_for_another_booking_is_a_conflict():
    a, b = _slots(12, 2)
    _book(a.slot_id, "P0002", "conflict-key")
    with pytest.raises(IdempotencyConflict):
        _book(b.slot_id, "P0002", "conflict-key")
    with pytest.raises(IdempotencyConflict):
        _book(a.slot_id, "P0003", "conflict-key")


def test_one_patient_holds_one_place_per_block():
    slot = _slots(14)[0]
    _book(slot.slot_id, "P0004", "first")
    with pytest.raises(AlreadyBooked):
        _book(slot.slot_id, "P0004", "second")


def test_a_cancelled_place_can_be_booked_again():
    # S0's unique rule kept the cancelled token, so a full block stayed full for ever
    slot = _slots(15)[0]
    booked = [_book(slot.slot_id, f"P{i + 1:04d}", f"cancel-{i}") for i in range(slot.capacity)]
    with pytest.raises(BlockFull):
        _book(slot.slot_id, "P0040", "cancel-full")
    with get_sessionmaker().begin() as s:
        service.release_slot(s, booked[1].appt_id)
    again = _book(slot.slot_id, "P0040", "cancel-again")
    assert again.token_no == booked[1].token_no


def test_database_refuses_a_token_above_capacity_or_a_duplicate_even_if_code_is_wrong():
    slot = _slots(16)[0]
    _book(slot.slot_id, "P0005", "db-rule")
    with get_sessionmaker()() as s, pytest.raises(Exception, match="exceeds capacity"):
        s.add(
            Appointment(
                patient_id="P0006",
                slot_id=slot.slot_id,
                token_no=slot.capacity + 1,
                idempotency_key="db-rule-over",
                booked_by="test",
            )
        )
        s.flush()
    with get_sessionmaker()() as s, pytest.raises(Exception, match="uq_appointment_active_token"):
        s.add(
            Appointment(
                patient_id="P0006",
                slot_id=slot.slot_id,
                token_no=1,
                idempotency_key="db-rule-dup",
                booked_by="test",
            )
        )
        s.flush()


def test_unknown_or_started_block_is_refused():
    with pytest.raises(SlotNotFound):
        _book("no-such-block", "P0007", "missing")
    slot = _slots(17)[0]
    with get_sessionmaker().begin() as s, pytest.raises(BlockStarted):
        reserve_slot(
            s,
            slot_id=slot.slot_id,
            patient_id="P0007",
            idem_key="started",
            booked_by="test",
            now=slot.starts_at + timedelta(minutes=1),
        )


def test_search_gives_three_doctors_with_next_block_and_skips_full_blocks():
    with get_sessionmaker()() as s:
        found = service.search_doctors(s, "SP01")
    assert len(found) == 3
    assert found == sorted(found, key=lambda c: c.block_start)
    assert all(c.places_left > 0 for c in found)
    # Fill the first doctor's next block: the cached read is invalidated and it drops out
    first = found[0]
    with get_sessionmaker()() as s:
        cap = s.get(Slot, first.slot_id).capacity
        used = s.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.slot_id == first.slot_id, Appointment.status != "cancelled")
        )
    for i in range(cap - used):
        _book(first.slot_id, f"P{i + 41:04d}", f"fill-{i}")
    now = datetime.now(UTC)
    with get_sessionmaker()() as s:
        blocks = service.list_slots(s, first.doctor_id, now, now + timedelta(days=14))
    assert first.slot_id not in {b.slot_id for b in blocks}


def test_late_block_opens_one_ticket_and_only_with_patients_waiting():
    slot = _slots(18)[0]
    _book(slot.slot_id, "P0008", "late")
    too_early = slot.ends_at + timedelta(minutes=29)
    late = slot.ends_at + timedelta(minutes=31)
    with get_sessionmaker().begin() as s:
        desk.scan_late_blocks(s, now=too_early)
        assert not s.scalar(
            select(func.count())
            .select_from(DeskTicket)
            .where(DeskTicket.slot_id == slot.slot_id, DeskTicket.kind == "late_block")
        )
        desk.scan_late_blocks(s, now=late)
        desk.scan_late_blocks(s, now=late)
        n = s.scalar(
            select(func.count())
            .select_from(DeskTicket)
            .where(DeskTicket.slot_id == slot.slot_id, DeskTicket.kind == "late_block")
        )
        assert n == 1
        s.execute(text("DELETE FROM desk_ticket WHERE kind = 'late_block'"))
