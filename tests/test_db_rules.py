"""Rules the database enforces on its own, whatever the application code does."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

AUDIT_ROW = """
INSERT INTO audit_event (actor_id, role, purpose, table_name, record_id, action, outcome, trace_id)
VALUES ('T1', 'doctor', 'test', 'patient', 'P0001', 'read', 'allowed', 't')
RETURNING event_id
"""


@pytest.fixture
def conn(database):
    """A connection whose work is always rolled back, so rule tests leave no rows behind."""
    with database.connect() as c:
        tx = c.begin()
        yield c
        tx.rollback()


def _savepoint_raises(conn, sql: str, params: dict | None = None, exc=DBAPIError) -> str:
    sp = conn.begin_nested()
    with pytest.raises(exc) as info:
        conn.execute(text(sql), params or {})
    sp.rollback()
    return str(info.value)


def test_audit_update_rejected(conn):
    event_id = conn.scalar(text(AUDIT_ROW))
    msg = _savepoint_raises(
        conn, "UPDATE audit_event SET actor_id='X' WHERE event_id=:id", {"id": event_id}
    )
    assert "append-only" in msg


def test_audit_delete_rejected(conn):
    event_id = conn.scalar(text(AUDIT_ROW))
    msg = _savepoint_raises(conn, "DELETE FROM audit_event WHERE event_id=:id", {"id": event_id})
    assert "append-only" in msg


def test_audit_truncate_rejected(conn):
    assert "append-only" in _savepoint_raises(conn, "TRUNCATE audit_event")


def _first_slot(conn) -> tuple[str, int]:
    row = conn.execute(text("SELECT slot_id, capacity FROM slot ORDER BY slot_id LIMIT 1")).one()
    return row.slot_id, row.capacity


def _book(conn, slot_id: str, token: int, key: str) -> None:
    conn.execute(
        text(
            "INSERT INTO appointment (patient_id, slot_id, token_no, idempotency_key, booked_by) "
            "VALUES ('P0001', :slot, :token, :key, 'test')"
        ),
        {"slot": slot_id, "token": token, "key": key},
    )


def test_same_token_twice_in_a_block_rejected(conn):
    slot_id, _ = _first_slot(conn)
    _book(conn, slot_id, 1, "k1")
    sp = conn.begin_nested()
    with pytest.raises(IntegrityError, match="uq_appointment_active_token"):
        _book(conn, slot_id, 1, "k2")
    sp.rollback()


def test_token_beyond_capacity_rejected(conn):
    slot_id, capacity = _first_slot(conn)
    sp = conn.begin_nested()
    with pytest.raises(DBAPIError, match="exceeds capacity"):
        _book(conn, slot_id, capacity + 1, "k-over")
    sp.rollback()


def test_idempotency_key_unique(conn):
    slot_id, _ = _first_slot(conn)
    _book(conn, slot_id, 1, "same-key")
    sp = conn.begin_nested()
    with pytest.raises(IntegrityError, match="idempotency_key"):
        _book(conn, slot_id, 2, "same-key")
    sp.rollback()


def _note(conn, signed: bool):
    slot_id, _ = _first_slot(conn)
    _book(conn, slot_id, 1, f"note-{signed}")
    appt_id = conn.scalar(
        text("SELECT appt_id FROM appointment WHERE idempotency_key=:k"), {"k": f"note-{signed}"}
    )
    doctor_id = conn.scalar(text("SELECT doctor_id FROM slot WHERE slot_id=:s"), {"s": slot_id})
    encounter_id = conn.scalar(
        text("INSERT INTO encounter (appt_id, doctor_id) VALUES (:a, :d) RETURNING encounter_id"),
        {"a": appt_id, "d": doctor_id},
    )
    return conn.scalar(
        text(
            "INSERT INTO clinical_note (encounter_id, doctor_id, soap_json, signed_at) "
            "VALUES (:e, :d, '{}'::jsonb, CASE WHEN :signed THEN now() END) RETURNING note_id"
        ),
        {"e": encounter_id, "d": doctor_id, "signed": signed},
    )


def test_signed_note_is_immutable(conn):
    note_id = _note(conn, signed=True)
    msg = _savepoint_raises(
        conn,
        "UPDATE clinical_note SET soap_json=jsonb_build_object('a', 1) WHERE note_id=:id",
        {"id": note_id},
    )
    assert "immutable" in msg
    msg = _savepoint_raises(conn, "DELETE FROM clinical_note WHERE note_id=:id", {"id": note_id})
    assert "immutable" in msg


def test_unsigned_draft_can_change(conn):
    note_id = _note(conn, signed=False)
    conn.execute(
        text("UPDATE clinical_note SET soap_json=jsonb_build_object('a', 1) WHERE note_id=:id"),
        {"id": note_id},
    )
