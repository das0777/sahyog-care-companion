"""Egress replay: 200 realistic outbound payloads and a leak detector independent of the scrubber.

Payloads are built from seeded patients with identifiers planted in many formats. The detector knows
the ground truth (every planted value) and searches the text the model adapter actually received.
It shares no code or word lists with sahyog.safety.deid, so a scrubber bug cannot hide itself.
"""

import random
import re
from dataclasses import dataclass, field
from datetime import date

from faker import Faker
from sqlalchemy import select
from sqlalchemy.orm import Session

from sahyog.models import Doctor, Patient

CITIES_PINS = [("Pune", "411038"), ("Mumbai", "400058"), ("Nagpur", "440010"), ("Nashik", "422005")]
FACTS = [
    "HbA1c 7.2%",
    "TSH 3.1 mIU/L",
    "creatinine 1.1 mg/dL",
    "LDL 142 mg/dL",
    "haemoglobin 11.8 g/dL",
    "platelets 1,50,000 /cumm",
    "vitamin D 18 ng/mL",
    "fasting sugar 126 mg/dL",
    "BP 150/95 mmHg",
    "ECG shows normal sinus rhythm",
]
MEDICINES = ["Metformin 500 mg", "Atorvastatin 10 mg", "Amlodipine 5 mg", "Levothyroxine 50 mcg"]
TEST_DATES = ["12/03/2026", "2026-07-21", "05 Aug 2026"]
SYMPTOMS = ["cough for a week", "knee pain while walking", "burning in the stomach after meals"]
# Third parties whose names are unlikely to be in any name list: only NER can catch these
UNLISTED_NAMES = [
    "Zoravar Bedi",
    "Tenzin Norbu",
    "Lalremruati Pachuau",
    "Fatima Shaikh",
    "Aloysius Fernandes",
    "Thangam Muthiah",
    "Wangchuk Bhutia",
    "Irfan Qureshi",
    "Jyotirmoy Haldar",
    "Phurba Lepcha",
]
# The detector's own short list of surnames that are also English words; matched only as part
# of the full name, so the word itself ("Date of test") is not counted as a leak
DETECTOR_COMMON_WORDS = {
    "date",
    "more",
    "master",
    "merchant",
    "tailor",
    "contractor",
    "doctor",
    "lucky",
    "deep",
    "harsh",
    "bath",
    "oak",
    "tank",
    "mall",
    "loyal",
}


@dataclass
class Planted:
    kind: str  # name, phone, abha, dob, email, pincode
    value: str
    unlisted: bool = False  # a name outside the gazetteer, reported separately


@dataclass
class Payload:
    id: str
    patient_id: str
    text: str
    planted: list[Planted]
    clinical: list[str] = field(default_factory=list)


@dataclass
class Leak:
    payload_id: str
    kind: str
    value: str


def build_payloads(session: Session, *, n: int = 200, random_seed: int = 42) -> list[Payload]:
    patients = session.execute(select(Patient).order_by(Patient.patient_id).limit(n)).scalars()
    doctors = session.execute(select(Doctor.name).order_by(Doctor.doctor_id).limit(50)).scalars()
    patients, doctors = list(patients), list(doctors)
    if len(patients) < n:
        raise RuntimeError(f"need {n} seeded patients, found {len(patients)}: run `make seed`")
    rng = random.Random(random_seed)
    fake = Faker("en_IN")
    fake.seed_instance(random_seed)
    return [_payload(i, p, rng, fake, doctors) for i, p in enumerate(patients)]


def _payload(i: int, p: Patient, rng: random.Random, fake: Faker, doctors: list[str]) -> Payload:
    planted = [Planted("name", p.name)]
    fact, med, test_date = rng.choice(FACTS), rng.choice(MEDICINES), rng.choice(TEST_DATES)
    phone = _phone_format(p.phone, i)
    abha = _abha_format(p.abha_id, i)
    dob = _dob_format(p.dob, i)
    third_unlisted = (i // 8) % 2 == 0  # half the third-party names are outside any list
    third = rng.choice(UNLISTED_NAMES) if third_unlisted else fake.name()
    first, last = p.name.split()[0], p.name.split()[-1]
    email = f"{first.lower()}.{last.lower()}{i}@example.com"
    city, pin = rng.choice(CITIES_PINS)
    doctor = rng.choice(doctors)
    t = i % 8
    if t == 0:
        text = f"{p.name}, age {_age(p.dob)}, phone {phone}. {rng.choice(SYMPTOMS)}; {fact}."
        planted += [Planted("phone", p.phone)]
    elif t == 1:
        text = (
            f"Question from {p.name} (ABHA {abha}): my report from {test_date} says {fact}. "
            "Is that normal?"
        )
        planted += [Planted("abha", p.abha_id)]
    elif t == 2:
        text = (
            f"Consultation note. Patient: {p.name}, DOB {dob}. Seen by {doctor}. {fact}. "
            f"Plan: {med}. Call back on {phone}."
        )
        planted += [
            Planted("dob", p.dob.isoformat()),
            Planted("phone", p.phone),
            Planted("name", doctor.removeprefix("Dr. ")),
        ]
    elif t == 3:
        text = (
            f"I am {third} calling for my mother {p.name}. Her number is {phone}, "
            f"email {email}. {fact}; she takes {med}."
        )
        planted += [
            Planted("phone", p.phone),
            Planted("email", email),
            Planted("name", third, third_unlisted),
        ]
    elif t == 4:
        text = (
            f"{p.name} lives near {city} {pin}, ABHA {abha}. Reports dated {test_date}: "
            f"{fact}. Born {dob}."
        )
        planted += [
            Planted("pincode", pin),
            Planted("abha", p.abha_id),
            Planted("dob", p.dob.isoformat()),
        ]
    elif t == 5:
        text = (
            f"mera naam {p.name.lower()} hai, {phone} pe call karo. {fact} aaya hai. "
            f"{med} le raha hoon."
        )
        planted += [Planted("phone", p.phone)]
    elif t == 6:
        text = f"patient {p.name.lower()} dob {dob}, abha {abha}. {fact}. Next review {test_date}."
        planted += [Planted("dob", p.dob.isoformat()), Planted("abha", p.abha_id)]
    else:
        # Every other one names the third party with no relationship word in front
        lead = f"and her husband {third}" if i % 16 == 7 else f"came in with {third};"
        text = f"{p.name} {lead} both have {fact}. Contact {email} or {phone}."
        planted += [
            Planted("name", third, third_unlisted),
            Planted("email", email),
            Planted("phone", p.phone),
        ]
    clinical = [fact] + ([med] if med in text else []) + ([test_date] if test_date in text else [])
    return Payload(f"eg-{i + 1:03d}", p.patient_id, text, planted, clinical)


# ---- detector ----------------------------------------------------------------------------


def detect(payload: Payload, sent: str) -> list[Leak]:
    leaks = []
    lowered = sent.lower()
    number_runs = [re.sub(r"\D", "", r) for r in re.findall(r"[+\d][\d\s\-]*\d", sent)]
    for item in payload.planted:
        if _leaked(item, sent, lowered, number_runs):
            leaks.append(
                Leak(payload.id, item.kind + (" (unlisted)" if item.unlisted else ""), item.value)
            )
    # Generic catch-alls, in case a payload carries something the ground truth missed
    for run in number_runs:
        if len(run) >= 10:
            leaks.append(Leak(payload.id, "long number", run))
    for m in re.finditer(r"[\w.+-]+@[\w-]+\.[\w.]+", sent):
        leaks.append(Leak(payload.id, "email pattern", m.group()))
    return _dedupe(leaks)


def _leaked(item: Planted, sent: str, lowered: str, number_runs: list[str]) -> bool:
    if item.kind == "name":
        if item.value.lower() in lowered:
            return True
        parts = [w for w in item.value.split() if len(w) >= 3]
        for w in parts:
            if w.lower() in DETECTOR_COMMON_WORDS:
                continue
            if re.search(rf"\b{re.escape(w.lower())}\b", lowered):
                return True
        return False
    if item.kind == "phone":
        target = re.sub(r"\D", "", item.value)[-10:]
        return any(target in run for run in number_runs)
    if item.kind == "abha":
        target = re.sub(r"\D", "", item.value)
        return any(target in run for run in number_runs)
    if item.kind == "dob":
        d = date.fromisoformat(item.value)
        forms = [
            d.isoformat(),
            f"{d.day:02d}/{d.month:02d}/{d.year}",
            f"{d.day} {d:%b} {d.year}",
            f"{d:%B} {d.day}, {d.year}",
            f"{d.day}/{d.month}/{d.year}",
        ]
        return any(f.lower() in lowered for f in forms)
    if item.kind in ("email", "pincode"):
        return item.value.lower() in lowered
    raise ValueError(item.kind)


def _dedupe(leaks: list[Leak]) -> list[Leak]:
    seen, out = set(), []
    for leak in leaks:
        key = (leak.kind, leak.value)
        if key not in seen:
            seen.add(key)
            out.append(leak)
    return out


def _phone_format(phone: str, i: int) -> str:
    d = re.sub(r"\D", "", phone)[-10:]
    return [f"+91 {d}", f"+91{d}", f"0{d}", f"{d[:5]} {d[5:]}", f"+91-{d[:2]}-{d[2:6]}-{d[6:]}", d][
        i % 6
    ]


def _abha_format(abha: str, i: int) -> str:
    d = re.sub(r"\D", "", abha)
    return [abha, d, f"{d[:2]} {d[2:6]} {d[6:10]} {d[10:]}"][i % 3]


def _dob_format(dob: date, i: int) -> str:
    return [
        dob.isoformat(),
        f"{dob.day:02d}/{dob.month:02d}/{dob.year}",
        f"{dob.day} {dob:%b} {dob.year}",
        f"{dob:%B} {dob.day}, {dob.year}",
    ][i % 4]


def _age(dob: date) -> int:
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
