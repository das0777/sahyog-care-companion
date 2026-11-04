import os

# Point the whole app at the test database before anything reads settings
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://sahyog:sahyog-dev@localhost:5433/sahyog_test"
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from sahyog.auth import Role, issue_token  # noqa: E402
from sahyog.config import get_settings  # noqa: E402
from sahyog.db import get_engine, get_sessionmaker  # noqa: E402
from sahyog.main import app  # noqa: E402
from sahyog.seed.generate import Scale, seed  # noqa: E402

# Small but complete: every specialty gets a doctor, some consents are expired
TEST_SCALE = Scale(doctors=60, patients=60, days=2, consents=10, expired_consents=3)


@pytest.fixture(scope="session", autouse=True)
def database():
    url = os.environ["DATABASE_URL"]
    engine = get_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = url
    command.upgrade(cfg, "head")
    with get_sessionmaker()() as session, session.begin():
        seed(session, random_seed=get_settings().seed_random_seed, scale=TEST_SCALE)
    yield engine


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def bearer(role: Role, actor_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(role, actor_id)}"}
