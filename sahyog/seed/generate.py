"""Deterministic synthetic seed. No real person's data: every name, ABHA ID and phone is generated.

Same random seed → identical rows. Only dates move: booking blocks start the day after the seed
runs, and consent expiry is relative to now, so counts and the fingerprint stay the same.
"""

import hashlib
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from faker import Faker
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from sahyog.models import (
    Clinic,
    Consent,
    Doctor,
    MedicineStock,
    Patient,
    Slot,
    Specialty,
)
from sahyog.seed.catalogue import (
    BLOCK_HOURS,
    CLINICS,
    GLOBAL_RED_FLAGS,
    MEDICINES,
    SPECIALTIES,
)

# Every seeded table, children first. audit_event is never cleared: audit history is permanent.
SEEDED_TABLES = [
    "prescription",
    "clinical_note",
    "encounter",
    "appointment",
    "doc_chunk",
    "document",
    "consent",
    "slot",
    "medicine_stock",
    "patient",
    "doctor",
    "specialty",
    "clinic",
]


@dataclass(frozen=True)
class Scale:
    doctors: int = 500
    patients: int = 1000
    days: int = 14
    consents: int = 50
    expired_consents: int = 10


@dataclass(frozen=True)
class SeedResult:
    counts: dict[str, int]
    fingerprint: str


def seed(session: Session, *, random_seed: int, scale: Scale = Scale(), tz: str = "Asia/Kolkata"):
    rng = random.Random(random_seed)
    fake = Faker("en_IN")
    fake.seed_instance(random_seed)
    zone = ZoneInfo(tz)
    first_day = datetime.now(zone).date() + timedelta(days=1)

    session.execute(text(f"TRUNCATE {', '.join(SEEDED_TABLES)} CASCADE"))

    clinics = [
        {"clinic_id": cid, "name": name, "city": city, "opens_at": time(9), "closes_at": time(17)}
        for cid, name, city in CLINICS
    ]
    specialties = [
        {
            "specialty_id": sid,
            "name": name,
            "red_flag_rules": {
                "global": GLOBAL_RED_FLAGS,
                "specific": phrases,
                "reviewed_by": None,
            },
        }
        for sid, name, _, phrases in SPECIALTIES
    ]
    doctors = _doctors(rng, fake, scale.doctors)
    slots = _slots(rng, doctors, first_day, scale.days, zone)
    patients = _patients(rng, fake, scale.patients)
    consents = _consents(patients, scale)
    stock = _stock(rng, first_day)

    for model, rows in [
        (Clinic, clinics),
        (Specialty, specialties),
        (Doctor, doctors),
        (Patient, patients),
        (Slot, slots),
        (Consent, consents),
        (MedicineStock, stock),
    ]:
        if rows:
            session.execute(insert(model), rows)

    counts = {
        "specialty": len(specialties),
        "clinic": len(clinics),
        "doctor": len(doctors),
        "slot": len(slots),
        "patient": len(patients),
        "consent": len(consents),
        "medicine_stock": len(stock),
    }
    return SeedResult(counts=counts, fingerprint=_fingerprint(doctors, patients, slots, stock))


def _doctors(rng: random.Random, fake: Faker, n: int) -> list[dict]:
    ids = [s[0] for s in SPECIALTIES]
    weights = [s[2] for s in SPECIALTIES]
    rows = []
    for i in range(1, n + 1):
        # Every specialty gets at least one doctor before weighting takes over
        specialty_id = ids[i - 1] if i <= len(ids) else rng.choices(ids, weights)[0]
        languages = ["en"] + rng.sample(["hi", "mr"], k=rng.randint(1, 2))
        rows.append(
            {
                "doctor_id": f"D{i:04d}",
                "name": f"Dr. {fake.name()}",
                "specialty_id": specialty_id,
                "clinic_id": CLINICS[rng.randrange(len(CLINICS))][0],
                "languages": sorted(languages),
                "synthetic": True,
            }
        )
    return rows


def _slots(rng, doctors, first_day: date, days: int, zone: ZoneInfo) -> list[dict]:
    rows = []
    for d in doctors:
        for offset in range(days):
            day = first_day + timedelta(days=offset)
            for hour in BLOCK_HOURS:
                starts = datetime.combine(day, time(hour), zone)
                rows.append(
                    {
                        "slot_id": f"{d['doctor_id']}-{day:%Y%m%d}-{hour:02d}",
                        "doctor_id": d["doctor_id"],
                        "clinic_id": d["clinic_id"],
                        "starts_at": starts,
                        "ends_at": starts + timedelta(hours=1),
                        "capacity": rng.randint(4, 6),
                    }
                )
    return rows


def _patients(rng: random.Random, fake: Faker, n: int) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        digits = f"{rng.randrange(10**14):014d}"
        rows.append(
            {
                "patient_id": f"P{i:04d}",
                "abha_id": f"{digits[:2]}-{digits[2:6]}-{digits[6:10]}-{digits[10:]}",
                "name": fake.name(),
                "dob": fake.date_between(date(1940, 1, 1), date(2020, 12, 31)),
                # +91 55 is not an Indian mobile range, so no real person can ever be texted
                "phone": f"+91 55{rng.randrange(10**8):08d}",
                "language": rng.choices(["en", "hi", "mr"], [4, 4, 2])[0],
                "synthetic": True,
            }
        )
    return rows


def _consents(patients: list[dict], scale: Scale) -> list[dict]:
    now = datetime.now(UTC)
    rows = []
    for i, p in enumerate(patients[: scale.consents]):
        expired = i >= scale.consents - scale.expired_consents
        rows.append(
            {
                "patient_id": p["patient_id"],
                "grantee_id": f"CG{i + 1:04d}",
                "scope": "records:read",
                "purpose": "caregiving",
                "expires_at": now - timedelta(days=10) if expired else now + timedelta(days=180),
            }
        )
    return rows


def _stock(rng: random.Random, as_of: date) -> list[dict]:
    rows = []
    for cid, _, _ in CLINICS:
        for mid, name, composition, price in MEDICINES:
            rows.append(
                {
                    "medicine_id": mid,
                    "clinic_id": cid,
                    "name": name,
                    "composition": composition,
                    "price": price,
                    # About one in ten items is out of stock, so W3 stock flags have cases
                    "qty": 0 if rng.random() < 0.1 else rng.randint(5, 200),
                    "as_of": as_of,
                }
            )
    return rows


def _fingerprint(doctors, patients, slots, stock) -> str:
    """Hash of every generated value except dates, so two runs on any day can be compared."""
    h = hashlib.sha256()
    for d in doctors:
        h.update(f"{d['doctor_id']}|{d['name']}|{d['specialty_id']}|{d['clinic_id']}".encode())
    for p in patients:
        h.update(f"{p['patient_id']}|{p['abha_id']}|{p['name']}|{p['dob']}|{p['phone']}".encode())
    for s in slots:
        h.update(f"{s['doctor_id']}|{s['starts_at']:%H}|{s['capacity']}".encode())
    for m in stock:
        h.update(f"{m['medicine_id']}|{m['clinic_id']}|{m['qty']}".encode())
    return h.hexdigest()[:16]
