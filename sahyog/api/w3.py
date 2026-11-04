"""W3 endpoints. A doctor acts only on their own encounters, and a paused run lives in the
checkpointer, so any API replica can resume it."""

import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from sahyog import audit
from sahyog.api.idempotency import held
from sahyog.auth import AuthContext, Role, get_auth_context
from sahyog.config import get_settings
from sahyog.db import get_session, get_sessionmaker
from sahyog.graphs.runtime import get_scribe_runtime
from sahyog.graphs.w3 import unresolved
from sahyog.models import Appointment, ClinicalNote, Encounter, ScribeJob, Slot
from sahyog.storage import get_minio

router = APIRouter(prefix="/w3", tags=["w3"])
MAX_AUDIO_BYTES = 50 * 1024 * 1024
AUDIO_TYPES = {".m4a", ".mp3", ".wav", ".webm", ".ogg", ".aiff", ".flac"}


class EncounterIn(BaseModel):
    appt_id: uuid.UUID


class TranscriptIn(BaseModel):
    transcript: str = Field(min_length=5, max_length=20000)


class ResumeIn(BaseModel):
    decision: Literal["sign", "reject", "edit"]
    edits: dict[str, Any] | None = None
    comments: str | None = Field(default=None, max_length=2000)


def _doctor(ctx: AuthContext, record_id: str, action: str) -> None:
    if ctx.role != Role.DOCTOR:
        _deny(ctx, record_id, action)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Doctors only")


def _deny(ctx, record_id, action) -> None:
    audit.record(
        ctx, table="encounter", record_id=record_id, action=action, outcome=audit.Outcome.DENIED
    )


def _allow(ctx, record_id, action) -> None:
    audit.record(
        ctx, table="encounter", record_id=record_id, action=action, outcome=audit.Outcome.ALLOWED
    )


@router.post("/encounters", status_code=status.HTTP_201_CREATED)
def open_encounter(
    body: EncounterIn,
    ctx: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    _doctor(ctx, str(body.appt_id), "open")
    row = session.execute(
        select(Appointment, Slot.doctor_id)
        .join(Slot, Appointment.slot_id == Slot.slot_id)
        .where(Appointment.appt_id == body.appt_id)
    ).first()
    if row is None or row[1] != ctx.actor_id:
        _deny(ctx, str(body.appt_id), "open")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such appointment for this doctor")
    encounter = Encounter(appt_id=body.appt_id, doctor_id=ctx.actor_id)
    session.add(encounter)
    session.commit()
    _allow(ctx, str(encounter.encounter_id), "open")
    return {"encounter_id": str(encounter.encounter_id)}


def _own_encounter(session: Session, ctx: AuthContext, encounter_id: uuid.UUID, action: str):
    _doctor(ctx, str(encounter_id), action)
    encounter = session.get(Encounter, encounter_id)
    if encounter is None or encounter.doctor_id != ctx.actor_id:
        _deny(ctx, str(encounter_id), action)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such encounter")
    return encounter


def _queue(session: Session, ctx: AuthContext, encounter_id, transcript=None) -> dict[str, str]:
    thread_id = str(uuid.uuid4())
    session.add(
        ScribeJob(
            encounter_id=encounter_id,
            thread_id=thread_id,
            transcript=transcript,
            trace_id=ctx.trace_id,
        )
    )
    session.commit()
    _allow(ctx, str(encounter_id), "scribe")
    return {"thread_id": thread_id}


@router.post("/encounters/{encounter_id}/audio", status_code=status.HTTP_202_ACCEPTED)
async def upload_audio(
    encounter_id: uuid.UUID,
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    encounter = _own_encounter(session, ctx, encounter_id, "audio")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in AUDIO_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unsupported audio type")
    data = await file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Recording is over 50 MB")
    uri = f"encounters/{encounter_id}{suffix}"
    await run_in_threadpool(
        get_minio().put_object,
        get_settings().audio_bucket,
        uri,
        _stream(data),
        len(data),
    )
    encounter.audio_uri = uri
    session.commit()
    return _queue(session, ctx, encounter_id)


def _stream(data: bytes):
    import io

    return io.BytesIO(data)


@router.post("/encounters/{encounter_id}/transcript", status_code=status.HTTP_202_ACCEPTED)
def typed_dictation(
    encounter_id: uuid.UUID,
    body: TranscriptIn,
    ctx: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    _own_encounter(session, ctx, encounter_id, "transcript")
    return _queue(session, ctx, encounter_id, body.transcript)


def _job_for_doctor(session, ctx, thread_id: uuid.UUID, action: str) -> ScribeJob:
    _doctor(ctx, str(thread_id), action)
    row = session.execute(
        select(ScribeJob, Encounter.doctor_id)
        .join(Encounter, ScribeJob.encounter_id == Encounter.encounter_id)
        .where(ScribeJob.thread_id == str(thread_id))
    ).first()
    if row is None or row[1] != ctx.actor_id:
        _deny(ctx, str(thread_id), action)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such draft")
    return row[0]


@router.get("/{thread_id}/draft")
def read_draft(
    thread_id: uuid.UUID,
    ctx: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = _job_for_doctor(session, ctx, thread_id, "draft")
    _allow(ctx, str(thread_id), "draft")
    out: dict[str, Any] = {"thread_id": str(thread_id), "status": job.status}
    if job.status in ("queued", "running", "failed"):
        return out | {"reason": job.reason}
    snapshot = get_scribe_runtime().graph.get_state(_config(thread_id))
    pauses = [i.value for t in snapshot.tasks for i in t.interrupts]
    if pauses:
        return out | pauses[0] | {"transcript": job.transcript}
    return out | {
        "status": snapshot.values.get("status"),
        "note_id": snapshot.values.get("note_id"),
    }


@router.post("/{thread_id}/resume")
def resume(
    thread_id: uuid.UUID,
    body: ResumeIn,
    ctx: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _job_for_doctor(session, ctx, thread_id, "resume")
    graph = get_scribe_runtime().graph
    config = _config(thread_id)
    with held(f"scribe:{thread_id}"):
        snapshot = graph.get_state(config)
        if snapshot.values.get("status") == "signed":
            _deny(ctx, str(thread_id), "edit:signed")
            raise HTTPException(status.HTTP_423_LOCKED, "This note is signed and can't change")
        if not any(i for t in snapshot.tasks for i in t.interrupts):
            raise HTTPException(status.HTTP_409_CONFLICT, "This draft isn't ready for review")
        if body.decision == "sign":
            open_gaps = unresolved(snapshot.values, body.edits)
            if open_gaps:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    {"message": "Fill or remove these before signing", "gaps": open_gaps},
                )
        if body.decision == "reject" and not body.comments:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Say what to change")
        _allow(ctx, str(thread_id), body.decision)
        result = graph.invoke(
            Command(resume=body.model_dump() | {"trace_id": ctx.trace_id}),
            config,
            durability="sync",
        )
    if result.get("status") == "signed":
        return {"status": "signed", "note_id": result["note_id"], "version": result["version"]}
    if result.get("status") == "failed":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The redraft failed; try again")
    pause = [i.value for t in graph.get_state(config).tasks for i in t.interrupts]
    return {"status": "review"} | (pause[0] if pause else {})


def _config(thread_id: uuid.UUID) -> dict:
    return {"configurable": {"thread_id": f"w3-{thread_id}"}}


@router.get("/notes/{note_id}")
def read_note(
    note_id: uuid.UUID,
    ctx: AuthContext = Depends(get_auth_context),
) -> dict[str, Any]:
    with get_sessionmaker()() as session:
        note = session.get(ClinicalNote, note_id)
        allowed = note is not None and (
            ctx.role == Role.PHARMACIST
            or (ctx.role == Role.DOCTOR and note.doctor_id == ctx.actor_id)
        )
    audit.record(
        ctx,
        table="clinical_note",
        record_id=str(note_id),
        action="read",
        outcome=audit.Outcome.ALLOWED if allowed else audit.Outcome.DENIED,
    )
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such note")
    if ctx.role == Role.PHARMACIST:
        return {"note_id": str(note.note_id), "medicines": note.soap_json["medicines"]}
    return {
        "note_id": str(note.note_id),
        "soap": note.soap_json["soap"],
        "medicines": note.soap_json["medicines"],
        "version": note.version,
        "signed_at": note.signed_at.isoformat(),
        "hash": note.hash,
        "edit_history": note.edit_history,
        "review_seconds": note.review_seconds,
    }
