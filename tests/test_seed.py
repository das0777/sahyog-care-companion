from sqlalchemy import func, select, text

from sahyog.config import get_settings
from sahyog.db import get_sessionmaker
from sahyog.models import Consent, Doctor, Specialty
from sahyog.seed.catalogue import BLOCK_HOURS, CLINICS, SPECIALTIES
from sahyog.seed.generate import Scale, seed
from tests.conftest import TEST_SCALE


def _run(scale: Scale = TEST_SCALE):
    with get_sessionmaker()() as session, session.begin():
        return seed(session, random_seed=get_settings().seed_random_seed, scale=scale)


def test_seed_is_repeatable():
    first, second = _run(), _run()
    assert first.counts == second.counts
    assert first.fingerprint == second.fingerprint


def test_different_seed_gives_different_data():
    with get_sessionmaker()() as session, session.begin():
        other = seed(session, random_seed=7, scale=TEST_SCALE)
    assert other.fingerprint != _run().fingerprint  # _run restores the standard seed


def test_counts_match_scale():
    counts = _run().counts
    assert counts["specialty"] == len(SPECIALTIES) == 38
    assert counts["clinic"] == len(CLINICS) == 12
    assert counts["doctor"] == TEST_SCALE.doctors
    assert counts["slot"] == TEST_SCALE.doctors * TEST_SCALE.days * len(BLOCK_HOURS)
    assert counts["patient"] == TEST_SCALE.patients


def test_full_scale_slot_count_matches_stage_doc():
    full = Scale()
    assert full.doctors * full.days * len(BLOCK_HOURS) == 42_000


def test_every_specialty_has_a_doctor_and_red_flags():
    _run()
    with get_sessionmaker()() as session:
        covered = session.scalar(select(func.count(func.distinct(Doctor.specialty_id))))
        rules = session.scalars(select(Specialty.red_flag_rules)).all()
    assert covered == 38
    assert all(r["global"] and r["reviewed_by"] is None for r in rules)


def test_expired_consents_seeded():
    _run()
    with get_sessionmaker()() as session:
        expired = session.scalar(
            select(func.count()).select_from(Consent).where(Consent.expires_at < func.now())
        )
    assert expired == TEST_SCALE.expired_consents


def test_phones_are_outside_mobile_ranges():
    _run()
    with get_sessionmaker()() as session:
        phones = session.scalars(text("SELECT phone FROM patient")).all()
    assert phones and all(p.startswith("+91 55") for p in phones)


def test_seed_keeps_audit_history(database):
    with database.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_event (actor_id, role, purpose, table_name, record_id, action,"
                " outcome, trace_id) VALUES ('SEEDTEST', 'doctor', 'test', 'patient', 'P0001',"
                " 'read', 'allowed', 'seed-test')"
            )
        )
    _run()
    with database.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM audit_event WHERE trace_id='seed-test'"))
