"""W1 endpoints. Stateless: a paused run lives in the checkpointer, and the client resumes it with
the thread id it was given. The patient always comes from the token, never the body."""

import logging
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from sahyog import audit
from sahyog.api.idempotency import held, once
from sahyog.auth import AuthContext, Role, get_auth_context
from sahyog.db import get_sessionmaker
from sahyog.graphs import w1_messages as msg
from sahyog.graphs.runtime import get_runtime
from sahyog.graphs.w1 import book_key
from sahyog.safety.language import detect
from sahyog.scheduling import desk

log = logging.getLogger("sahyog.w1")
router = APIRouter(prefix="/w1", tags=["w1"])

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=64)]


class TriageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    age: int | None = Field(default=None, ge=0, le=120)
    language: Literal["en", "hi", "mixed"] | None = None


class ResumeIn(BaseModel):
    slot_id: str | None = Field(default=None, max_length=24)
    answer: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def one_of(self) -> "ResumeIn":
        if (self.slot_id is None) == (self.answer is None):
            raise ValueError("send exactly one of slot_id or answer")
        return self


@router.post("/triage")
def triage(
    body: TriageIn,
    idempotency_key: IdempotencyKey,
    ctx: AuthContext = Depends(get_auth_context),
):
    if ctx.role != Role.PATIENT:
        audit.record(
            ctx,
            table="w1_thread",
            record_id=ctx.actor_id,
            action="triage",
            outcome=audit.Outcome.DENIED,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a patient can start triage")

    def work() -> tuple[int, dict[str, Any]]:
        thread_id = str(uuid.uuid4())
        audit.record(
            ctx,
            table="w1_thread",
            record_id=thread_id,
            action="triage",
            outcome=audit.Outcome.ALLOWED,
        )
        state = {
            "patient_id": ctx.actor_id,
            "trace_id": ctx.trace_id,
            "thread_id": thread_id,
            "turns": [body.text],
            "request_age": body.age,
            "language": body.language,
        }
        return _run(ctx, thread_id, state, [body.text], body.language)

    return once(ctx, idempotency_key, {"path": "triage", **body.model_dump()}, work)


@router.post("/{thread_id}/resume")
def resume(
    thread_id: uuid.UUID,
    body: ResumeIn,
    idempotency_key: IdempotencyKey,
    ctx: AuthContext = Depends(get_auth_context),
):
    from langgraph.types import Command

    tid = str(thread_id)

    def work() -> tuple[int, dict[str, Any]]:
        # One step at a time per thread, even when two different keys arrive together
        with held(f"thread:{tid}"):
            graph = get_runtime().graph
            snapshot = graph.get_state(_config(tid))
            values = snapshot.values or {}
            if values.get("patient_id") != ctx.actor_id:
                _deny(ctx, tid, "resume")
                # Same reply whether the thread is missing or someone else's
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your conversation")
            pause = _pause(snapshot)
            if pause is None:
                raise HTTPException(status.HTTP_409_CONFLICT, "This conversation has finished")
            if pause["kind"] == "clarify":
                if body.answer is None:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Expected an answer")
                value = {"answer": body.answer, "trace_id": ctx.trace_id}
            else:
                offered = {c["slot_id"] for c in pause["candidates"]}
                if body.slot_id not in offered:
                    _deny(ctx, tid, "resume:bad_slot")
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_CONTENT, "That block was not offered"
                    )
                value = {
                    "slot_id": body.slot_id,
                    "book_key": book_key(ctx.actor_id, idempotency_key),
                    "trace_id": ctx.trace_id,
                }
            audit.record(
                ctx,
                table="w1_thread",
                record_id=tid,
                action="resume",
                outcome=audit.Outcome.ALLOWED,
            )
            return _run(ctx, tid, Command(resume=value), values["turns"], values.get("language"))

    return once(ctx, idempotency_key, {"path": f"resume:{tid}", **body.model_dump()}, work)


def _run(ctx, thread_id, graph_input, turns, language) -> tuple[int, dict[str, Any]]:
    """Run to the next pause or the end. An unexpected failure goes to a person, never a bare 500:
    the patient may be describing an emergency that nobody has ruled out."""
    graph = get_runtime().graph
    config = _config(thread_id)
    try:
        graph.invoke(graph_input, config, durability="sync")
        return _reply(thread_id, graph.get_state(config))
    except Exception:  # noqa: BLE001 - the fail-closed path above
        log.exception("W1 run failed, handing off (trace %s)", ctx.trace_id)
    lang = language or detect(" ".join(turns))
    with get_sessionmaker().begin() as session:
        ticket = desk.open_ticket(
            session,
            kind="safety_unchecked",
            reason="Assistant failed during this conversation; not ruled out as an emergency",
            reason_codes=["run_failed"],
            patient_id=ctx.actor_id,
            patient_text=" . ".join(turns),
            thread_id=thread_id,
            trace_id=ctx.trace_id,
        )
    return 503, {
        "thread_id": thread_id,
        "status": "handed_to_desk",
        "handoff": True,
        "message": msg.message("desk", lang),
        "ticket_id": str(ticket),
    }


def _reply(thread_id: str, snapshot) -> tuple[int, dict[str, Any]]:
    v = snapshot.values
    pause = _pause(snapshot)
    if pause and pause["kind"] == "clarify":
        return 200, {"thread_id": thread_id, "status": "clarify", "question": pause["question"]}
    if pause:
        out = {
            "thread_id": thread_id,
            "status": "awaiting_choice",
            "specialty": {"id": v["specialty_id"], "name": v["specialty_name"]},
            "candidates": pause["candidates"],
        }
        if v.get("notice"):
            out["notice"] = v["notice"]
        return 200, out
    if v.get("status") == "booked":
        return 200, {"thread_id": thread_id, "status": "booked", "message": v["message"]} | v[
            "appointment"
        ]
    out = {
        "thread_id": thread_id,
        "status": v["status"],
        "message": v["message"],
        "ticket_id": v["ticket_id"],
    }
    if v.get("service_unavailable"):
        return 503, out | {"handoff": True}
    return 200, out


def _pause(snapshot) -> dict | None:
    for task in snapshot.tasks:
        for i in task.interrupts:
            return i.value
    return None


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _deny(ctx: AuthContext, thread_id: str, action: str) -> None:
    audit.record(
        ctx, table="w1_thread", record_id=thread_id, action=action, outcome=audit.Outcome.DENIED
    )
