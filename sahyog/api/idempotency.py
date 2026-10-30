"""Every write takes an Idempotency-Key. The same key returns the first reply; the same key with a
different body gets 409. Concurrent retries wait their turn rather than racing: the lock is a
Postgres advisory lock, and waiters poll without holding a connection, so a burst of retries can't
starve the request doing the work."""

import hashlib
import json
import struct
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from sahyog.auth import AuthContext
from sahyog.db import get_engine, get_sessionmaker
from sahyog.models import IdempotencyRecord

LOCK_WAIT_S = 45.0
POLL_S = 0.05


@contextmanager
def held(name: str, *, wait_s: float = LOCK_WAIT_S) -> Iterator[None]:
    key = struct.unpack("q", hashlib.sha256(name.encode()).digest()[:8])[0]
    deadline = time.monotonic() + wait_s
    while True:
        conn = get_engine().connect()
        try:
            if conn.scalar(select(func.pg_try_advisory_lock(key))):
                conn.commit()
                try:
                    yield
                finally:
                    conn.execute(select(func.pg_advisory_unlock(key)))
                    conn.commit()
                return
        finally:
            conn.close()
        if time.monotonic() > deadline:
            raise HTTPException(status.HTTP_409_CONFLICT, "Still being processed; retry shortly")
        time.sleep(POLL_S)


def once(
    ctx: AuthContext, key: str, body: dict, work: Callable[[], tuple[int, dict[str, Any]]]
) -> JSONResponse:
    """Run `work` once for this actor and key. Rejected requests raise and are not remembered."""
    body_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    with held(f"idem:{ctx.actor_id}:{key}"):
        with get_sessionmaker()() as session:
            first = session.get(IdempotencyRecord, (ctx.actor_id, key))
        if first:
            if first.body_hash != body_hash:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "Idempotency key reused with a different body"
                )
            return JSONResponse(first.response, status_code=first.status_code)
        code, response = work()
        with get_sessionmaker().begin() as session:
            session.add(
                IdempotencyRecord(
                    actor_id=ctx.actor_id,
                    key=key,
                    body_hash=body_hash,
                    status_code=code,
                    response=response,
                )
            )
    return JSONResponse(response, status_code=code)
