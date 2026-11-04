"""Scheduling tools for W1: find doctors, read free blocks, reserve and release a place.

A slot is a block with capacity (E2.4). `reserve_slot` locks the block row, so concurrent bookings
queue up and each gets the lowest free token; the database's unique indexes and capacity trigger
hold even if this code is wrong. Replies quote the block and token, never an exact minute.
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from functools import cache

import redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sahyog.config import get_settings
from sahyog.models import Appointment, Clinic, Doctor, Slot

log = logging.getLogger("sahyog.scheduling")

SLOT_CACHE_TTL_S = 30
SEARCH_WINDOW_DAYS = 14
ACTIVE = Appointment.status != "cancelled"


class SchedulingError(Exception):
    pass


class SlotNotFound(SchedulingError):
    pass


class BlockFull(SchedulingError):
    pass


class BlockStarted(SchedulingError):
    pass


class AlreadyBooked(SchedulingError):
    """This patient already holds a place in this block."""


class IdempotencyConflict(SchedulingError):
    """The key was already used for a different booking."""


class NotActive(SchedulingError):
    """The appointment is past the point where it can be changed."""


@dataclass(frozen=True)
class FreeBlock:
    slot_id: str
    doctor_id: str
    block_start: str
    block_end: str
    places_left: int


@dataclass(frozen=True)
class Candidate:
    doctor_id: str
    doctor_name: str
    clinic: str
    city: str
    languages: list[str]
    slot_id: str
    block_start: str
    block_end: str
    places_left: int


@dataclass(frozen=True)
class Reservation:
    appt_id: uuid.UUID
    slot_id: str
    block_start: datetime
    block_end: datetime
    token_no: int
    replayed: bool = False


def search_doctors(
    session: Session, specialty_id: str, *, language: str | None = None, limit: int = 3
) -> list[Candidate]:
    """Doctors of a specialty with a free block, soonest first; patient language breaks ties."""
    doctors = session.execute(
        select(Doctor, Clinic)
        .join(Clinic, Doctor.clinic_id == Clinic.clinic_id)
        .where(Doctor.specialty_id == specialty_id)
        .order_by(Doctor.doctor_id)
    ).all()
    now = _now()
    found = []
    for doctor, clinic in doctors:
        blocks = list_slots(session, doctor.doctor_id, now, now + timedelta(SEARCH_WINDOW_DAYS))
        if blocks:
            found.append((doctor, clinic, blocks[0]))
    found.sort(
        key=lambda f: (f[2].block_start, language not in f[0].languages, f[0].doctor_id),
    )
    return [
        Candidate(
            doctor_id=d.doctor_id,
            doctor_name=d.name,
            clinic=c.name,
            city=c.city,
            languages=list(d.languages),
            slot_id=b.slot_id,
            block_start=b.block_start,
            block_end=b.block_end,
            places_left=b.places_left,
        )
        for d, c, b in found[:limit]
    ]


def list_slots(session: Session, doctor_id: str, start: datetime, end: datetime) -> list[FreeBlock]:
    """Free blocks for a doctor. Read through Redis for 30 s; a stale read only ever costs a retry,
    because `reserve_slot` decides against the database."""
    key = f"{_cache_prefix(doctor_id)}{start:%Y%m%d}:{end:%Y%m%d}"
    cached = _cache_get(key)
    if cached is not None:
        return [
            b for b in map(lambda r: FreeBlock(**r), cached) if b.block_start > start.isoformat()
        ]
    used = (
        select(Appointment.slot_id, func.count().label("n"))
        .where(ACTIVE)
        .group_by(Appointment.slot_id)
        .subquery()
    )
    rows = session.execute(
        select(Slot, func.coalesce(used.c.n, 0))
        .outerjoin(used, used.c.slot_id == Slot.slot_id)
        .where(
            Slot.doctor_id == doctor_id,
            Slot.starts_at > start,
            Slot.starts_at < end,
            func.coalesce(used.c.n, 0) < Slot.capacity,
        )
        .order_by(Slot.starts_at)
    ).all()
    blocks = [
        FreeBlock(
            slot_id=s.slot_id,
            doctor_id=doctor_id,
            block_start=s.starts_at.astimezone(UTC).isoformat(),
            block_end=s.ends_at.astimezone(UTC).isoformat(),
            places_left=s.capacity - n,
        )
        for s, n in rows
    ]
    _cache_set(key, [asdict(b) for b in blocks])
    return blocks


def reserve_slot(
    session: Session,
    *,
    slot_id: str,
    patient_id: str,
    idem_key: str,
    booked_by: str,
    now: datetime | None = None,
) -> Reservation:
    """Book one place. The caller owns the transaction and commits. The same key returns the first
    booking; the key with a different patient or block raises IdempotencyConflict."""
    existing = _by_key(session, idem_key, patient_id, slot_id)
    if existing:
        return existing
    slot = session.execute(select(Slot).where(Slot.slot_id == slot_id).with_for_update()).scalar()
    if slot is None:
        raise SlotNotFound(slot_id)
    # Checked again under the lock: a concurrent retry of this key may have just committed
    existing = _by_key(session, idem_key, patient_id, slot_id)
    if existing:
        return existing
    if slot.starts_at <= (now or _now()):
        raise BlockStarted(slot_id)
    active = session.execute(
        select(Appointment.token_no, Appointment.patient_id).where(
            Appointment.slot_id == slot_id, ACTIVE
        )
    ).all()
    if any(a.patient_id == patient_id for a in active):
        raise AlreadyBooked(slot_id)
    used = {a.token_no for a in active}
    if len(used) >= slot.capacity:
        raise BlockFull(slot_id)
    token = next(t for t in range(1, slot.capacity + 1) if t not in used)
    appt = Appointment(
        patient_id=patient_id,
        slot_id=slot_id,
        token_no=token,
        idempotency_key=idem_key,
        booked_by=booked_by,
    )
    try:
        with session.begin_nested():
            session.add(appt)
            session.flush()
    except IntegrityError as e:
        # Same key, different block: the two bookings did not share a block lock
        if "idempotency_key" in str(e.orig):
            raise IdempotencyConflict(idem_key) from e
        raise
    _invalidate(slot.doctor_id)
    return Reservation(appt.appt_id, slot_id, slot.starts_at, slot.ends_at, token)


def release_slot(session: Session, appt_id: uuid.UUID) -> Appointment:
    """Cancel a booking and free its place. Replayable: an already cancelled one stays cancelled."""
    appt = session.execute(
        select(Appointment).where(Appointment.appt_id == appt_id).with_for_update()
    ).scalar()
    if appt is None:
        raise SlotNotFound(str(appt_id))
    if appt.status == "cancelled":
        return appt
    if appt.status != "booked":
        raise NotActive(appt.status)
    appt.status = "cancelled"
    session.flush()
    doctor_id = session.scalar(select(Slot.doctor_id).where(Slot.slot_id == appt.slot_id))
    _invalidate(doctor_id)
    return appt


def _by_key(session: Session, key: str, patient_id: str, slot_id: str) -> Reservation | None:
    row = session.execute(
        select(Appointment, Slot)
        .join(Slot, Appointment.slot_id == Slot.slot_id)
        .where(Appointment.idempotency_key == key)
    ).first()
    if row is None:
        return None
    appt, slot = row
    if appt.patient_id != patient_id or appt.slot_id != slot_id:
        raise IdempotencyConflict(key)
    return Reservation(appt.appt_id, slot_id, slot.starts_at, slot.ends_at, appt.token_no, True)


def _now() -> datetime:
    return datetime.now(UTC)


# ---- cache: optional by design, a Redis problem falls through to Postgres --------------------


@cache
def _redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.2)


def _cache_prefix(doctor_id: str | None) -> str:
    # By database, so the test database never reads the dev database's blocks
    return f"slots:{get_settings().database_url.rsplit('/', 1)[-1]}:{doctor_id}:"


def _cache_get(key: str) -> list[dict] | None:
    try:
        raw = _redis().get(key)
    except redis.RedisError:
        log.warning("slot cache read failed; using Postgres")
        return None
    return json.loads(raw) if raw else None


def _cache_set(key: str, value: list[dict]) -> None:
    try:
        _redis().set(key, json.dumps(value), ex=SLOT_CACHE_TTL_S)
    except redis.RedisError:
        log.warning("slot cache write failed")


def _invalidate(doctor_id: str | None) -> None:
    try:
        client = _redis()
        for key in client.scan_iter(f"{_cache_prefix(doctor_id)}*"):
            client.delete(key)
    except redis.RedisError:
        log.warning("slot cache invalidation failed; entries expire within 30 s")
