import uuid

import jwt
import pytest

from sahyog import audit
from sahyog.auth import Role
from tests.conftest import bearer


def _audit_rows(client, record_id: str) -> list[dict]:
    resp = client.get(f"/audit?record_id={record_id}", headers=bearer(Role.COMPLIANCE, "COMP01"))
    assert resp.status_code == 200
    return resp.json()


def test_health_reports_each_dependency(client):
    body = client.get("/health").json()
    assert body == {"status": "ok", "postgres": "ok", "redis": "ok", "minio": "ok"}


def test_missing_and_bad_tokens_rejected(client):
    assert client.get("/me").status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    assert client.get("/me", headers=bad).status_code == 401
    forged = jwt.encode(
        {"sub": "P0001", "role": "doctor", "exp": 9999999999},
        "a-different-secret-that-is-also-32-bytes-long",
    )
    assert client.get("/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_me_returns_auth_context(client):
    resp = client.get("/me", headers={**bearer(Role.DOCTOR, "D0001"), "X-Purpose": "follow_up"})
    body = resp.json()
    assert body["actor_id"] == "D0001" and body["role"] == "doctor"
    assert body["purpose"] == "follow_up"
    assert body["trace_id"] == resp.headers["X-Trace-Id"]


def test_patient_reads_own_record(client):
    resp = client.get("/patients/P0001", headers=bearer(Role.PATIENT, "P0001"))
    assert resp.status_code == 200
    assert resp.json()["patient_id"] == "P0001"


@pytest.mark.parametrize(
    ("role", "actor", "expected"),
    [
        (Role.PATIENT, "P0001", 403),
        (Role.DOCTOR, "D0001", 200),
        (Role.DESK, "DESK01", 200),
        (Role.CAREGIVER, "CG0002", 403),  # consent enforcement arrives in S4
        (Role.PHARMACIST, "PH01", 403),
        (Role.COMPLIANCE, "COMP01", 403),
    ],
)
def test_access_rule_for_another_patients_record(client, role, actor, expected):
    assert client.get("/patients/P0002", headers=bearer(role, actor)).status_code == expected


def test_every_attempt_is_audited_including_denials(client):
    trace = uuid.uuid4().hex
    client.get("/patients/P0003", headers={**bearer(Role.PATIENT, "P0001"), "X-Trace-Id": trace})
    client.get("/patients/P0003", headers={**bearer(Role.DOCTOR, "D0001"), "X-Trace-Id": trace})
    rows = [r for r in _audit_rows(client, "P0003") if r["trace_id"] == trace]
    assert [(r["actor_id"], r["role"], r["outcome"]) for r in rows] == [
        ("P0001", "patient", "denied"),
        ("D0001", "doctor", "allowed"),
    ]
    assert rows[1]["purpose"] == "treatment"  # role default when no X-Purpose is sent


def test_audit_query_needs_compliance_and_is_itself_audited(client):
    assert (
        client.get("/audit?record_id=P0004", headers=bearer(Role.DOCTOR, "D0001")).status_code
        == 403
    )
    rows = _audit_rows(client, "P0004")
    assert [(r["table_name"], r["action"], r["outcome"]) for r in rows] == [
        ("audit_event", "query", "denied"),
        ("audit_event", "query", "allowed"),
    ]


def test_failed_audit_write_fails_the_read(client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit, "add", broken)
    resp = client.get("/patients/P0005", headers=bearer(Role.DOCTOR, "D0001"))
    assert resp.status_code == 500
    assert "P0005" not in resp.text


def test_unknown_patient_is_404_but_still_audited(client):
    resp = client.get("/patients/P9999", headers=bearer(Role.DOCTOR, "D0001"))
    assert resp.status_code == 404
    assert _audit_rows(client, "P9999")[0]["outcome"] == "allowed"


def test_doctor_directory_filters(client):
    resp = client.get(
        "/doctors?specialty=Cardiology&limit=5", headers=bearer(Role.PATIENT, "P0001")
    )
    assert resp.status_code == 200
    assert resp.json() and all(d["specialty"] == "Cardiology" for d in resp.json())
