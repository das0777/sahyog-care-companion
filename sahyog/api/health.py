from fastapi import APIRouter, Response, status
from redis import Redis
from sqlalchemy import text

from sahyog.config import get_settings
from sahyog.db import get_engine
from sahyog.storage import get_minio

router = APIRouter(tags=["platform"])


def _check(fn) -> str:
    try:
        fn()
        return "ok"
    except Exception as exc:  # noqa: BLE001 - health reports any failure, never raises
        return f"error: {type(exc).__name__}"


def _postgres() -> None:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))


def _redis() -> None:
    Redis.from_url(get_settings().redis_url, socket_timeout=2).ping()


def _minio() -> None:
    s = get_settings()
    for bucket in (s.report_bucket, s.audio_bucket):
        if not get_minio().bucket_exists(bucket):
            raise LookupError(bucket)


@router.get("/health")
def health(response: Response) -> dict:
    checks = {"postgres": _check(_postgres), "redis": _check(_redis), "minio": _check(_minio)}
    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "degraded", **checks}
