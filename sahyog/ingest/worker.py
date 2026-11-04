"""The ingest worker: a bounded pool sharing the Postgres queue. A separate process from the API,
so OCR and embedding can't starve triage."""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from redis import Redis
from redis.exceptions import RedisError

from sahyog.config import get_settings
from sahyog.db import get_sessionmaker
from sahyog.graphs.runtime import get_scribe_runtime
from sahyog.graphs.w2_ingest import IngestDeps, build_ingest
from sahyog.ingest.embedding import get_embedder
from sahyog.ingest.jobs import claim, give_up_on_expired, run_job
from sahyog.scribe.jobs import claim_scribe, purge_audio, run_scribe_job

log = logging.getLogger("sahyog.ingest")
READY_FILE = Path("/tmp/worker-ready")  # noqa: S108 - inside the container, for its health check
POLL_S = 0.5
AUDIO_SWEEP_S = 600
HEARTBEAT_TTL_S = 30


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    os.environ.setdefault("OMP_THREAD_LIMIT", "2")  # Tesseract, per page
    settings = get_settings()
    sessions = get_sessionmaker()
    embedder = get_embedder()  # loads or downloads the model before taking any work
    embedder.query("ready")
    graph = build_ingest(IngestDeps(embedder, sessions))
    READY_FILE.touch()
    log.info("worker ready: %s workers, model %s", settings.ingest_workers, embedder.model)

    def loop() -> None:
        while True:
            try:
                give_up_on_expired(sessions)
                with sessions.begin() as session:
                    job = claim(session, lease_s=settings.ingest_lease_s)
                if job:
                    run_job(graph, sessions, job)
                    continue
                with sessions.begin() as session:
                    scribe = claim_scribe(session, lease_s=settings.ingest_lease_s)
                if scribe:
                    run_scribe_job(get_scribe_runtime().graph, sessions, scribe)
                    continue
                time.sleep(POLL_S)
            except Exception:  # noqa: BLE001 - e.g. Postgres restarting; keep the pool alive
                log.exception("worker loop error")
                time.sleep(POLL_S * 4)

    def sweep() -> None:
        while True:
            try:
                purge_audio(sessions)
            except Exception:  # noqa: BLE001 - the bucket's expiry rule is the backstop
                log.exception("audio sweep error")
            time.sleep(AUDIO_SWEEP_S)

    def heartbeat() -> None:
        client = Redis.from_url(settings.redis_url, socket_timeout=2)
        while True:
            try:
                client.set("worker:heartbeat", "1", ex=HEARTBEAT_TTL_S)
            except RedisError:
                log.warning("heartbeat write failed")
            time.sleep(HEARTBEAT_TTL_S / 3)

    with ThreadPoolExecutor(settings.ingest_workers + 2) as pool:
        pool.submit(sweep)
        pool.submit(heartbeat)
        for _ in range(settings.ingest_workers):
            pool.submit(loop)


if __name__ == "__main__":
    main()
