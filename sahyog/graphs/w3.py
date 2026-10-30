"""W3 scribe: dictation to a stock-flagged SOAP draft, paused for the doctor. Nothing is written to
the record until the doctor signs. Grounding is code (sahyog/scribe/grounding.py), not a prompt.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from sahyog import audit
from sahyog.auth import AuthContext, Role
from sahyog.graphs import w3_prompts as prompts
from sahyog.llm.gateway import ModelGateway
from sahyog.llm.schemas import MedicineList, SoapDraft
from sahyog.llm.types import ModelError
from sahyog.models import (
    Appointment,
    ClinicalNote,
    Encounter,
    Patient,
    Prescription,
    Slot,
    StockReservation,
)
from sahyog.safety.deid import KnownIdentity
from sahyog.scheduling import desk
from sahyog.scribe import grounding
from sahyog.scribe.stock import StockSource

MODEL_TIMEOUT_S = 30.0
SECTIONS = ("subjective", "objective", "assessment", "plan")


class ScribeState(TypedDict, total=False):
    thread_id: str
    encounter_id: str
    doctor_id: str
    patient_id: str
    clinic_id: str
    trace_id: str
    transcript: str
    turns: list[dict]
    comments: str | None
    soap: dict
    medicines: list[dict]
    gaps: list[dict]
    flags: list[str]
    status: str
    failure: str
    note_id: str
    started_review: str
    edit_history: list[dict]
    version: int


@dataclass
class ScribeDeps:
    gateway: ModelGateway
    stock: StockSource
    sessions: sessionmaker[Session]
    grounding_enabled: bool = True  # off only for the GUARDRAILS=off eval run


def build_w3(deps: ScribeDeps, checkpointer) -> Any:
    n = _Nodes(deps)
    g = StateGraph(ScribeState)
    for name in ("segment", "draft_soap", "extract_meds", "stock_check", "review", "store", "fail"):
        g.add_node(name, getattr(n, name))
    g.add_edge(START, "segment")
    g.add_edge("segment", "draft_soap")
    g.add_conditional_edges(
        "draft_soap", lambda s: "fail" if s.get("status") == "failed" else "extract_meds"
    )
    g.add_conditional_edges(
        "extract_meds", lambda s: "fail" if s.get("status") == "failed" else "stock_check"
    )
    g.add_edge("stock_check", "review")
    g.add_conditional_edges(
        "review",
        lambda s: {"sign": "store", "reject": "draft_soap", "recheck": "stock_check"}[s["status"]],
    )
    g.add_edge("store", END)
    g.add_edge("fail", END)
    return g.compile(checkpointer=checkpointer)


class _Nodes:
    def __init__(self, deps: ScribeDeps):
        self.d = deps

    def segment(self, state: ScribeState) -> ScribeState:
        return {
            "turns": [vars(t) for t in grounding.segment(state["transcript"])],
            "flags": [],
            "edit_history": [],
            "version": 1,
        }

    def draft_soap(self, state: ScribeState) -> ScribeState:
        try:
            draft = self._ask(
                prompts.DRAFT_TASK,
                prompts.DRAFT_SYSTEM,
                prompts.transcript_block(state["transcript"], state.get("comments")),
                SoapDraft,
                state,
            ).output
        except ModelError as e:
            return {"status": "failed", "failure": type(e).__name__}
        doctor = grounding.doctors_words([grounding.Turn(**t) for t in state["turns"]])
        comments = state.get("comments") or ""
        flags = []
        soap: dict[str, list[dict]] = {}
        for section in SECTIONS:
            lines = []
            only_doctor = section in ("assessment", "plan")
            source = doctor if only_doctor else state["transcript"]
            for line in getattr(draft, section):
                if self.d.grounding_enabled and not (
                    grounding.quoted(line.quote, source)
                    or (comments and grounding.quoted(line.quote, comments))
                ):
                    flags.append(f"Removed a {section} line that didn't quote the transcript")
                    continue
                text = line.text
                if self.d.grounding_enabled and only_doctor:
                    text, removed = grounding.clean_plan_line(
                        text, f"{state['transcript']} {comments}"
                    )
                    flags += [f"Removed '{r}': it wasn't said" for r in removed]
                lines.append({"text": text, "quote": line.quote})
            soap[section] = lines
        return {"soap": soap, "flags": flags, "status": "drafted"}

    def extract_meds(self, state: ScribeState) -> ScribeState:
        try:
            raw = self._ask(
                prompts.MEDS_TASK,
                prompts.MEDS_SYSTEM,
                prompts.transcript_block(state["transcript"], state.get("comments")),
                MedicineList,
                state,
            ).output.medicines
        except ModelError as e:
            return {"status": "failed", "failure": type(e).__name__}
        doctor = grounding.doctors_words([grounding.Turn(**t) for t in state["turns"]])
        comments = state.get("comments") or ""
        source = f"{doctor} {comments}".strip()
        if not self.d.grounding_enabled:
            meds = [
                {
                    "name": m.name,
                    "dose": m.dose,
                    "span": m.span,
                    "dose_gap": False,
                    "text": f"{m.name} {m.dose}".strip(),
                }
                for m in raw
            ]
            return {"medicines": meds, "gaps": []}
        grounded = grounding.ground_medicines([m.model_dump() for m in raw], source)
        flags = [f"Removed medicine '{d}': the doctor didn't say it" for d in grounded.dropped]
        return {
            "medicines": grounded.medicines,
            "gaps": grounded.gaps,
            "flags": state.get("flags", []) + flags,
        }

    def stock_check(self, state: ScribeState) -> ScribeState:
        checked = []
        for m in state["medicines"]:
            line = self.d.stock.lookup(m["name"], m.get("dose") or "", state["clinic_id"])
            checked.append(m | {"stock": vars(line)})
        return {"medicines": checked, "started_review": datetime.now(UTC).isoformat()}

    def review(self, state: ScribeState) -> ScribeState:
        """Only pauses, because LangGraph re-runs a node from its start on resume."""
        decision = interrupt(
            {
                "soap": state["soap"],
                "medicines": state["medicines"],
                "gaps": state["gaps"],
                "flags": state.get("flags", []),
            }
        )
        history = list(state.get("edit_history", []))
        history.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "decision": decision["decision"],
                "comments": decision.get("comments"),
                "edits": decision.get("edits"),
            }
        )
        out: ScribeState = {"edit_history": history, "trace_id": decision["trace_id"]}
        if decision["decision"] == "reject":
            return out | {
                "status": "reject",
                "comments": decision.get("comments"),
                "version": state.get("version", 1) + 1,
            }
        edits = decision.get("edits") or {}
        if edits.get("soap"):
            out["soap"] = edits["soap"]
        if "medicines" in edits:
            # The doctor's own decision: grounding doesn't apply to what they type here
            out["medicines"] = [
                {
                    "name": m["name"],
                    "dose": m.get("dose", ""),
                    "span": "doctor edit",
                    "dose_gap": False,
                    "text": f"{m['name']} {m.get('dose', '')}".strip(),
                    "stock": vars(
                        self.d.stock.lookup(m["name"], m.get("dose", ""), state["clinic_id"])
                    ),
                }
                for m in edits["medicines"]
            ]
            out["gaps"] = edits.get("gaps", [])
        if decision["decision"] == "edit":
            return out | {"status": "recheck"}
        return out | {"status": "sign"}

    def store(self, state: ScribeState) -> ScribeState:
        """The only place a clinical act is written, and it runs only after a signature."""
        encounter_id = uuid.UUID(state["encounter_id"])
        ctx = AuthContext(state["doctor_id"], Role.DOCTOR, "treatment", state["trace_id"])
        with self.d.sessions.begin() as session:
            existing = session.scalar(
                select(ClinicalNote.note_id).where(
                    ClinicalNote.encounter_id == encounter_id, ClinicalNote.signed_at.is_not(None)
                )
            )
            if existing:  # a retried node
                return {"status": "signed", "note_id": str(existing)}
            soap = {"soap": state["soap"], "medicines": state["medicines"]}
            now = datetime.now(UTC)
            digest = hashlib.sha256(
                json.dumps(soap, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            started = datetime.fromisoformat(state["started_review"])
            note = ClinicalNote(
                encounter_id=encounter_id,
                doctor_id=state["doctor_id"],
                soap_json=soap,
                version=state.get("version", 1),
                signed_at=now,
                hash=digest,
                edit_history=state.get("edit_history", []),
                review_seconds=(now - started).total_seconds(),
            )
            session.add(note)
            session.flush()
            for m in state["medicines"]:
                stock = m.get("stock") or {}
                medicine_id = stock.get("medicine_id") or "UNLISTED"
                session.add(
                    Prescription(note_id=note.note_id, medicine_id=medicine_id, dose=m["text"][:80])
                )
                if stock.get("medicine_id"):
                    session.add(
                        StockReservation(
                            note_id=note.note_id,
                            medicine_id=stock["medicine_id"],
                            clinic_id=state["clinic_id"],
                        )
                    )
            session.execute(
                update(Encounter).where(Encounter.encounter_id == encounter_id).values(ended_at=now)
            )
            audit.add(
                session,
                ctx,
                table="clinical_note",
                record_id=str(note.note_id),
                action="sign",
                outcome=audit.Outcome.ALLOWED,
            )
            desk.send_sms(
                session,
                patient_id=state["patient_id"],
                template="note_signed",
                variables={},
                trace_id=state["trace_id"],
            )
        return {"status": "signed", "note_id": str(note.note_id)}

    def fail(self, state: ScribeState) -> ScribeState:
        return {"status": "failed"}

    def _ask(self, task, system, prompt, schema, state: ScribeState):
        with self.d.sessions() as session:
            patient = session.get(Patient, state["patient_id"])
            known = KnownIdentity.from_patient(patient) if patient else None
        return self.d.gateway.complete(
            task,
            system=system,
            prompt=prompt,
            schema=schema,
            trace_id=state["trace_id"],
            patient=known,
            timeout_s=MODEL_TIMEOUT_S,
        )


def encounter_context(session: Session, encounter_id: uuid.UUID) -> dict | None:
    row = session.execute(
        select(Encounter, Appointment.patient_id, Slot.clinic_id)
        .join(Appointment, Encounter.appt_id == Appointment.appt_id)
        .join(Slot, Appointment.slot_id == Slot.slot_id)
        .where(Encounter.encounter_id == encounter_id)
    ).first()
    if row is None:
        return None
    encounter, patient_id, clinic_id = row
    return {
        "encounter_id": str(encounter.encounter_id),
        "doctor_id": encounter.doctor_id,
        "patient_id": patient_id,
        "clinic_id": clinic_id,
    }


def unresolved(state: dict, edits: dict | None) -> list[str]:
    """A signature can't leave a gap open: the doctor fills it or removes it."""
    edits = edits or {}
    gaps = edits["gaps"] if "gaps" in edits else state.get("gaps", [])
    meds = edits.get("medicines")
    if meds is not None:
        dose_gaps = [f"{m['name']}: no dose" for m in meds if not m.get("dose", "").strip()]
    else:
        dose_gaps = [m["text"] for m in state.get("medicines", []) if m["dose_gap"]]
    return [g["text"] for g in gaps] + dose_gaps
