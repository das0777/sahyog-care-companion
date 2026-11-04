"""W3 jobs on the worker: transcribe if there's audio, then run the graph to the doctor's review."""

import logging
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text, update

from sahyog import audit
from sahyog.auth import AuthContext, Role
from sahyog.config import get_settings
from sahyog.graphs.w3 import encounter_context
from sahyog.models import Encounter, ScribeJob
from sahyog.scribe.transcribe import transcribe
from sahyog.storage import get_minio

log = logging.getLogger("sahyog.scribe")
MAX_ATTEMPTS = 3
AUDIO_LIFETIME = timedelta(hours=24)

_CLAIM = text(
    """
    UPDATE scribe_job SET status = 'running', attempts = attempts + 1, lease_until = :lease_until
    WHERE job_id = (
        SELECT job_id FROM scribe_job
        WHERE (status = 'queued' OR (status = 'running' AND lease_until < now()))
          AND attempts < :max_attempts
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING job_id, encounter_id, thread_id, transcript, trace_id
    """
)


def claim_scribe(session, *, lease_s: int) -> dict | None:
    row = session.execute(
        _CLAIM,
        {
            "lease_until": datetime.now(UTC) + timedelta(seconds=lease_s),
            "max_attempts": MAX_ATTEMPTS,
        },
    ).first()
    return dict(row._mapping) if row else None


def run_scribe_job(graph, sessions, job: dict) -> None:
    """A failed attempt returns to the queue while attempts remain. The doctor's status says so."""
    try:
        transcript = job["transcript"]
        with sessions() as session:
            context = encounter_context(session, job["encounter_id"])
            encounter = session.get(Encounter, job["encounter_id"])
            audio_uri = encounter.audio_uri
        seconds = None
        if not transcript:
            started = time.perf_counter()
            transcript = _transcribe_object(audio_uri)
            seconds = time.perf_counter() - started
            if not transcript:
                _finish(sessions, job["job_id"], "failed", "No speech was found in the recording.")
                return
        with sessions.begin() as session:
            session.execute(
                update(ScribeJob)
                .where(ScribeJob.job_id == job["job_id"])
                .values(transcript=transcript, transcribe_seconds=seconds)
            )
        state = context | {
            "thread_id": job["thread_id"],
            "trace_id": job["trace_id"],
            "transcript": transcript,
        }
        result = graph.invoke(
            state, {"configurable": {"thread_id": f"w3-{job['thread_id']}"}}, durability="sync"
        )
        if result.get("status") == "failed":
            raise RuntimeError(result.get("failure", "draft failed"))
        _finish(sessions, job["job_id"], "review", None)
    except Exception:  # noqa: BLE001 - one bad recording must never take the worker down
        log.exception("scribe job failed: %s", job["job_id"])
        with sessions.begin() as session:
            attempts = session.scalar(
                select(ScribeJob.attempts).where(ScribeJob.job_id == job["job_id"])
            )
            if attempts < MAX_ATTEMPTS:
                session.execute(
                    update(ScribeJob)
                    .where(ScribeJob.job_id == job["job_id"])
                    .values(status="queued", lease_until=None)
                )
                return
        _finish(sessions, job["job_id"], "failed", "The draft couldn't be made. Please try again.")


def _finish(sessions, job_id, status: str, reason: str | None) -> None:
    with sessions.begin() as session:
        session.execute(
            update(ScribeJob)
            .where(ScribeJob.job_id == job_id)
            .values(status=status, reason=reason, lease_until=None)
        )


def _transcribe_object(uri: str) -> str:
    settings = get_settings()
    response = get_minio().get_object(settings.audio_bucket, uri)
    try:
        with tempfile.NamedTemporaryFile(suffix=Path(uri).suffix) as f:
            f.write(response.read())
            f.flush()
            return transcribe(Path(f.name))
    finally:
        response.close()
        response.release_conn()


def purge_audio(sessions, *, now: datetime | None = None) -> int:
    """E6.3: audio is gone within 24 h. The bucket's expiry rule is the backstop, and this sweep
    is what writes the audit event, so "who deleted it, and when" has an answer."""
    now = now or datetime.now(UTC)
    with sessions() as session:
        due = list(
            session.execute(
                select(Encounter).where(
                    Encounter.audio_uri.is_not(None),
                    Encounter.audio_deleted_at.is_(None),
                    Encounter.started_at < now - AUDIO_LIFETIME + timedelta(hours=1),
                )
            ).scalars()
        )
    bucket = get_settings().audio_bucket
    system = AuthContext("audio-sweep", Role.COMPLIANCE, "retention", uuid.uuid4().hex)
    for encounter in due:
        get_minio().remove_object(bucket, encounter.audio_uri)
        with sessions.begin() as session:
            session.execute(
                update(Encounter)
                .where(Encounter.encounter_id == encounter.encounter_id)
                .values(audio_deleted_at=now)
            )
            audit.add(
                session,
                system,
                table="encounter",
                record_id=str(encounter.encounter_id),
                action="audio:delete",
                outcome=audit.Outcome.ALLOWED,
            )
    return len(due)
