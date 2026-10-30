from sqlalchemy import select

from sahyog.auth import Role
from sahyog.config import get_settings
from sahyog.db import get_sessionmaker
from sahyog.models import AuditEvent
from tests.conftest import bearer


def test_screens_are_served_and_home_redirects(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/app/"
    page = client.get("/app/")
    assert page.status_code == 200 and "Sahyog" in page.text
    assert client.get("/app/app.js").status_code == 200


def test_dev_login_is_off_unless_asked_for(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "dev_login", False)
    assert client.post("/dev/login", json={"role": "desk", "actor_id": "D"}).status_code == 404
    monkeypatch.setattr(settings, "dev_login", True)
    r = client.post("/dev/login", json={"role": "desk", "actor_id": "DESK01"})
    assert r.status_code == 200 and r.json()["token"]
    assert client.post("/dev/login", json={"role": "boss", "actor_id": "D"}).status_code == 422


def test_lists_are_role_scoped_and_audited(client):
    for path, role, who in (
        ("/w1/appointments", Role.PATIENT, "P0001"),
        ("/w2/documents", Role.PATIENT, "P0001"),
        ("/w3/appointments", Role.DOCTOR, "D0001"),
    ):
        assert client.get(path, headers=bearer(role, who)).status_code == 200
        assert client.get(path, headers=bearer(Role.DESK, "DESK01")).status_code == 403
    with get_sessionmaker()() as s:
        assert s.execute(
            select(AuditEvent).where(
                AuditEvent.actor_id == "DESK01", AuditEvent.outcome == "denied"
            )
        ).first()
