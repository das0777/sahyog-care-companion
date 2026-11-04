import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from sahyog.api import desk, health, records, w1, w2
from sahyog.auth import new_trace_id
from sahyog.storage import ensure_buckets

log = logging.getLogger("sahyog")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        ensure_buckets()
    except Exception:  # noqa: BLE001 - /health reports MinIO problems; startup must not crash
        log.exception("Could not prepare object-store buckets")
    yield


app = FastAPI(title="Sahyog Care Companion", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    request.state.trace_id = (request.headers.get("x-trace-id") or new_trace_id())[:40]
    response = await call_next(request)
    response.headers["X-Trace-Id"] = request.state.trace_id
    return response


app.include_router(health.router)
app.include_router(records.router)
app.include_router(w1.router)
app.include_router(desk.router)
app.include_router(w2.router)
