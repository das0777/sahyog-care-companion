"""W2 ask: answers only from the caller's own chunks, with a citation on every sentence.

scope_guard → red_flag_rules → (refuse) → screen → (widen) → answer → safety_check → respond.

The patient filter is SQL built from the auth context, so no prompt or poisoned report can widen it.
The second pass runs beside retrieval to fit the time budget, and nothing from retrieval is used
until it has passed. Nothing reaches the patient until `safety_check` passes.
"""

import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sahyog import audit
from sahyog.auth import AuthContext, Role
from sahyog.graphs import w1_messages, w1_prompts, w2_messages, w2_prompts
from sahyog.ingest.embedding import Embedder
from sahyog.llm.gateway import ModelGateway
from sahyog.llm.schemas import AnswerDraft, ContextGrade, RedFlagSecondPass
from sahyog.llm.types import ModelError
from sahyog.models import Document, Patient
from sahyog.records.scope import can_read
from sahyog.records.search import Hit, retrieve_records
from sahyog.safety.deid import KnownIdentity
from sahyog.safety.language import detect
from sahyog.safety.red_flags import RedFlagEngine
from sahyog.safety.wording import asks_for_advice_on_records, clinical_answer
from sahyog.scheduling import desk

K = 8
K_WIDE = 16
MODEL_TIMEOUT_S = 15.0
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_PATIENT_ID = re.compile(r"\bP\d{4}\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


class AskState(TypedDict, total=False):
    # From the API: the token and the request
    ask_id: str
    actor_id: str
    role: str
    purpose: str
    trace_id: str
    patient_id: str
    question: str
    # Conversation
    language: str
    age_years: int | None
    fired: list[dict]
    hits: list[Hit]
    relevant: bool
    widened: bool
    draft: dict
    # Outcome
    status: str
    answer: str
    citations: list[dict]
    scan_warning: str | None
    ticket_id: str | None
    service_unavailable: bool
    block_reason: str


@dataclass
class AskDeps:
    gateway: ModelGateway
    engine: RedFlagEngine
    embedder: Embedder
    sessions: sessionmaker[Session]
    guardrails: bool = True  # off only for the GUARDRAILS=off eval run


def build_ask(deps: AskDeps) -> Any:
    n = _Nodes(deps)
    g = StateGraph(AskState)
    for name in (
        "scope_guard",
        "red_flag_rules",
        "emergency",
        "refuse",
        "screen",
        "widen",
        "answer",
        "safety_check",
        "not_found",
        "to_desk",
    ):
        g.add_node(name, getattr(n, name))
    g.add_edge(START, "scope_guard")
    g.add_conditional_edges(
        "scope_guard", lambda s: END if s.get("status") == "denied" else "red_flag_rules"
    )
    g.add_conditional_edges("red_flag_rules", _after_rules)
    g.add_conditional_edges("screen", _after_screen)
    g.add_edge("widen", "answer")
    g.add_conditional_edges("answer", _after_answer)
    g.add_edge("safety_check", END)
    for end in ("emergency", "refuse", "not_found", "to_desk"):
        g.add_edge(end, END)
    return g.compile()


def _after_rules(state: AskState) -> str:
    if state.get("fired"):
        return "emergency"
    return {"refuse": "refuse", "not_found": "not_found"}.get(state.get("status", ""), "screen")


def _after_screen(state: AskState) -> str:
    if state.get("status") == "to_desk":
        return "to_desk"
    if state.get("fired"):
        return "emergency"
    if not state.get("hits"):
        return "not_found"
    return "answer" if state.get("relevant") or state.get("widened") else "widen"


def _after_answer(state: AskState) -> str:
    return {"to_desk": "to_desk", "refuse": "refuse", "not_found": "not_found"}.get(
        state.get("status", ""), "safety_check"
    )


class _Nodes:
    def __init__(self, deps: AskDeps):
        self.d = deps

    def scope_guard(self, state: AskState) -> AskState:
        ctx = _ctx(state)
        with self.d.sessions() as session:
            allowed = not self.d.guardrails or can_read(session, ctx, state["patient_id"])
            patient = session.get(Patient, state["patient_id"]) if allowed else None
        audit.record(
            ctx,
            table="patient",
            record_id=state["patient_id"],
            action="ask",
            outcome=audit.Outcome.ALLOWED if allowed else audit.Outcome.DENIED,
        )
        if not allowed or patient is None:
            return {"status": "denied"}
        return {
            "language": detect(state["question"]),
            "age_years": _age(patient.dob) if patient.dob else None,
        }

    def red_flag_rules(self, state: AskState) -> AskState:
        decision = self.d.engine.check(
            state["question"], age_years=state.get("age_years"), enabled=self.d.guardrails
        )
        if decision.fired:
            return {
                "fired": [
                    {"rule": f.rule_id, "label": f.label, "kind": f.kind} for f in decision.fired
                ]
            }
        if any(p != state["patient_id"] for p in _PATIENT_ID.findall(state["question"])):
            # Answering could read the caller's own value back as if it were someone else's
            return {"status": "not_found"}
        return {"status": "refuse"} if asks_for_advice_on_records(state["question"]) else {}

    def screen(self, state: AskState) -> AskState:
        with ThreadPoolExecutor(2) as pool:
            check = pool.submit(self._second_pass, state) if self.d.guardrails else None
            found = pool.submit(self._retrieve_and_grade, state, K)
        try:
            flags = check.result() if check else None
        except ModelError as e:
            return {
                "status": "to_desk",
                "service_unavailable": True,
                "block_reason": f"Model safety check did not complete ({type(e).__name__}); not "
                "yet ruled out as an emergency",
            }
        if flags:
            return {
                "fired": [
                    {"rule": f"model:{f}", "label": flags.reason, "kind": "model"}
                    for f in flags.add_flags
                ]
            }
        hits, relevant = found.result()
        return {"hits": hits, "relevant": relevant}

    def _second_pass(self, state: AskState) -> RedFlagSecondPass | None:
        result = self._ask(
            w1_prompts.SECOND_PASS_TASK,
            w1_prompts.SECOND_PASS_SYSTEM,
            w1_prompts.wrap_patient_text([state["question"]], age_years=state.get("age_years")),
            RedFlagSecondPass,
            state,
        )
        return result.output if result.output.add_flags else None

    def _retrieve_and_grade(self, state: AskState, k: int) -> tuple[list[Hit], bool]:
        hits = self._retrieve(state, k)
        if not hits:
            return [], False
        try:
            grade = self._ask(
                w2_prompts.GRADE_TASK,
                w2_prompts.GRADE_SYSTEM,
                _prompt(state["question"], hits),
                ContextGrade,
                state,
            )
            return hits, grade.output.relevant
        except ModelError:
            # Grading only decides whether to widen: losing it costs quality, not safety
            return hits, True

    def _retrieve(self, state: AskState, k: int) -> list[Hit]:
        return retrieve_records(
            _ctx(state), state["patient_id"], state["question"], embedder=self.d.embedder, k=k
        )

    def widen(self, state: AskState) -> AskState:
        return {"hits": self._retrieve(state, K_WIDE), "widened": True}

    def answer(self, state: AskState) -> AskState:
        try:
            result = self._ask(
                w2_prompts.ANSWER_TASK,
                w2_prompts.ANSWER_SYSTEM,
                _prompt(state["question"], state["hits"]),
                AnswerDraft,
                state,
            )
        except ModelError as e:
            return {
                "status": "to_desk",
                "service_unavailable": True,
                "block_reason": f"Answer failed ({type(e).__name__})",
            }
        draft = result.output
        if draft.wants_diagnosis_or_dose:
            return {"status": "refuse"}
        if not draft.found or not draft.sentences:
            return {"status": "not_found"}
        return {"draft": draft.model_dump()}

    def safety_check(self, state: AskState) -> AskState:
        """Code, not a prompt. A failure blocks the whole answer, and logs an incident."""
        why = self._why_blocked(state)
        if why:
            return self._blocked(state, why)
        hits = state["hits"]
        cited: list[Hit] = []
        for s in state["draft"]["sentences"]:
            cited += [hits[i - 1] for i in s["excerpts"]]
        citations, seen = [], set()
        for h in cited:
            key = (h.doc_id, h.page)
            if key not in seen:
                seen.add(key)
                citations.append({"doc_id": str(h.doc_id), "page": h.page, "source": h.source})
        text = " ".join(s["text"].strip() for s in state["draft"]["sentences"])
        scanned = sorted({h.page for h in cited if h.source == "ocr"})
        warning = None
        if scanned:
            word = w2_messages.PAGE_WORD.get(state["language"], "page")
            warning = w2_messages.message(
                "scan_warning",
                state["language"],
                pages=f"{word} {', '.join(map(str, scanned))}",
            )
        return {
            "status": "answered",
            "answer": f"{text}\n\n{warning}" if warning else text,
            "citations": citations,
            "scan_warning": warning,
        }

    def _why_blocked(self, state: AskState) -> str | None:
        hits = state["hits"]
        sentences = state["draft"]["sentences"]
        for s in sentences:
            if not s["excerpts"]:
                return "sentence_without_citation"
            if any(i < 1 or i > len(hits) for i in s["excerpts"]):
                return "citation_out_of_range"
        cited_docs = {hits[i - 1].doc_id for s in sentences for i in s["excerpts"]}
        with self.d.sessions() as session:
            owners = session.execute(
                select(Document.doc_id, Document.patient_id).where(Document.doc_id.in_(cited_docs))
            ).all()
        if len(owners) != len(cited_docs) or any(o != state["patient_id"] for _, o in owners):
            return "foreign_document"
        own = {str(d) for d in cited_docs}
        for s in sentences:
            text = s["text"]
            if any(p != state["patient_id"] for p in _PATIENT_ID.findall(text)):
                return "foreign_patient_id"
            if any(u.lower() not in own for u in _UUID.findall(text)):
                return "foreign_document_id"
            chunks = " ".join(hits[i - 1].text for i in s["excerpts"])
            if not numbers(text) <= numbers(chunks):
                return "number_not_in_cited_text"
            if clinical_answer(text):
                return "clinical_wording"
        return None

    def _blocked(self, state: AskState, why: str) -> AskState:
        ctx = _ctx(state)
        with self.d.sessions.begin() as session:
            ticket = desk.open_ticket(
                session,
                kind="answer_blocked",
                reason=f"Answer blocked by the safety check: {why}",
                reason_codes=[why],
                patient_id=state["patient_id"],
                patient_text=state["question"],
                thread_id=state["ask_id"],
                trace_id=state["trace_id"],
            )
            audit.add(
                session,
                ctx,
                table="patient",
                record_id=state["patient_id"],
                action="ask:blocked",
                outcome=audit.Outcome.DENIED,
            )
        return {
            "status": "blocked",
            "answer": w2_messages.message("blocked", state["language"]),
            "ticket_id": str(ticket),
            "block_reason": why,
        }

    def emergency(self, state: AskState) -> AskState:
        fired = state["fired"]
        codes = [f["rule"] for f in fired][:10]
        with self.d.sessions.begin() as session:
            ticket = desk.open_ticket(
                session,
                kind="er",
                reason="; ".join(dict.fromkeys(f["label"] for f in fired))[:500],
                reason_codes=codes,
                patient_id=state["patient_id"],
                patient_text=state["question"],
                thread_id=state["ask_id"],
                trace_id=state["trace_id"],
            )
        name = "self_harm" if any("self_harm" in c for c in codes) else "emergency"
        return {
            "status": "emergency",
            "answer": w1_messages.message(name, state["language"]),
            "ticket_id": str(ticket),
        }

    def refuse(self, state: AskState) -> AskState:
        with self.d.sessions.begin() as session:
            ticket = desk.open_ticket(
                session,
                kind="advice_request",
                reason="Patient asked about their reports for a diagnosis or dose",
                reason_codes=["advice_request"],
                patient_id=state["patient_id"],
                patient_text=state["question"],
                thread_id=state["ask_id"],
                trace_id=state["trace_id"],
            )
        return {
            "status": "refused",
            "answer": w2_messages.message("refused", state["language"]),
            "ticket_id": str(ticket),
        }

    def not_found(self, state: AskState) -> AskState:
        return {
            "status": "not_found",
            "answer": w2_messages.message("not_found", state["language"]),
        }

    def to_desk(self, state: AskState) -> AskState:
        kind = "safety_unchecked" if "safety check" in state["block_reason"] else "model_failure"
        with self.d.sessions.begin() as session:
            ticket = desk.open_ticket(
                session,
                kind=kind,
                reason=state["block_reason"],
                reason_codes=[kind],
                patient_id=state["patient_id"],
                patient_text=state["question"],
                thread_id=state["ask_id"],
                trace_id=state["trace_id"],
            )
        return {
            "status": "handed_to_desk",
            "answer": w1_messages.message("desk", state["language"]),
            "ticket_id": str(ticket),
        }

    def _ask(self, task, system, prompt, schema, state: AskState):
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


def numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text.translate(_DEVANAGARI_DIGITS)))


def new_state(ctx: AuthContext, patient_id: str, question: str) -> AskState:
    return {
        "ask_id": str(uuid.uuid4()),
        "actor_id": ctx.actor_id,
        "role": ctx.role.value,
        "purpose": ctx.purpose,
        "trace_id": ctx.trace_id,
        "patient_id": patient_id,
        "question": question,
    }


def _ctx(state: AskState) -> AuthContext:
    return AuthContext(state["actor_id"], Role(state["role"]), state["purpose"], state["trace_id"])


def _prompt(question: str, hits: list[Hit]) -> str:
    block = w2_prompts.excerpts_block([(h.text, h.source == "ocr") for h in hits])
    return f"{block}\n\n{w2_prompts.question_block(question)}"


def _age(dob: date) -> int:
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
