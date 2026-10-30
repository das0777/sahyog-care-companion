"""W1 Find my doctor: free text in, and out to the emergency desk, a person or a booked block.

Order matters. Fixed rules run before any model. The model second pass can only add flags, and if
it fails the patient goes to the desk: a safety check that did not run does not count as a pass.
A clarifying answer goes back through the whole gate with the first message. Identity comes from
state set by the API from the token, never from model output. Nodes that pause do nothing else,
because LangGraph re-runs a node from its start on resume.
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, interrupt
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from sahyog.config import get_settings
from sahyog.graphs import w1_messages as msg
from sahyog.graphs import w1_prompts as prompts
from sahyog.llm.gateway import ModelGateway
from sahyog.llm.schemas import ClarifyQuestion, RedFlagSecondPass, SpecialtyMatch
from sahyog.llm.types import ModelError
from sahyog.models import Doctor, Patient, Specialty
from sahyog.safety.deid import KnownIdentity
from sahyog.safety.language import detect
from sahyog.safety.red_flags import RedFlagEngine
from sahyog.safety.wording import asks_for_advice, sounds_clinical
from sahyog.scheduling import desk, service

LOW_CONFIDENCE = 0.6
MODEL_TIMEOUT_S = 10.0
EMERGENCY_MEDICINE = "SP38"
_db_retry = RetryPolicy(max_attempts=2, retry_on=OperationalError)


class W1State(TypedDict, total=False):
    # Set by the API from the token
    patient_id: str
    trace_id: str
    thread_id: str
    # The conversation
    turns: list[str]
    request_age: int | None
    age_years: int | None
    language: str
    # Gate
    fired: list[dict]
    # Match
    early_match: dict | None
    specialty_id: str
    specialty_name: str
    alternative: str | None
    confidence: float
    clarify_count: int
    question: str
    # Routing to a person
    handoff_kind: str
    handoff_reason: str
    handoff_message: str
    # Booking
    candidates: list[dict]
    notice: str | None
    slot_id: str
    book_key: str
    appointment: dict
    # Outcome
    status: str
    message: str
    ticket_id: str
    service_unavailable: bool


@dataclass
class W1Deps:
    gateway: ModelGateway
    engine: RedFlagEngine
    sessions: sessionmaker[Session]
    rules_enabled: bool = True


def build_w1(deps: W1Deps, checkpointer) -> Any:
    n = _Nodes(deps)
    g = StateGraph(W1State)
    g.add_node("intake", n.intake)
    g.add_node("red_flag_rules", n.red_flag_rules)
    g.add_node("second_pass", n.second_pass)
    g.add_node("er_handoff", n.er_handoff, retry_policy=_db_retry)
    g.add_node("match_specialty", n.match_specialty)
    g.add_node("ask", n.ask)
    g.add_node("await_answer", n.await_answer)
    g.add_node("desk_handoff", n.desk_handoff, retry_policy=_db_retry)
    g.add_node("shortlist", n.shortlist, retry_policy=_db_retry)
    g.add_node("pick", n.pick)
    g.add_node("book", n.book, retry_policy=_db_retry)

    g.add_edge(START, "intake")
    g.add_edge("intake", "red_flag_rules")
    g.add_conditional_edges(
        "red_flag_rules", _after_rules, ["er_handoff", "desk_handoff", "second_pass"]
    )
    g.add_conditional_edges(
        "second_pass", _after_second_pass, ["er_handoff", "desk_handoff", "match_specialty"]
    )
    g.add_conditional_edges(
        "match_specialty",
        _after_match,
        ["er_handoff", "desk_handoff", "ask", "shortlist"],
    )
    g.add_conditional_edges("ask", _after_ask, ["desk_handoff", "await_answer"])
    g.add_edge("await_answer", "red_flag_rules")
    g.add_conditional_edges("shortlist", _after_shortlist, ["desk_handoff", "pick"])
    g.add_edge("pick", "book")
    g.add_conditional_edges("book", _after_book, ["shortlist", END])
    g.add_edge("er_handoff", END)
    g.add_edge("desk_handoff", END)
    return g.compile(checkpointer=checkpointer)


# ---- routing -----------------------------------------------------------------------------


def _after_rules(state: W1State) -> str:
    if state.get("handoff_kind"):
        return "desk_handoff"
    return "er_handoff" if state.get("fired") else "second_pass"


def _after_second_pass(state: W1State) -> str:
    if state.get("fired"):
        return "er_handoff"
    return "desk_handoff" if state.get("handoff_kind") else "match_specialty"


def _after_match(state: W1State) -> str:
    if state.get("fired"):
        return "er_handoff"
    if state.get("handoff_kind"):
        return "desk_handoff"
    return "ask" if state["confidence"] < LOW_CONFIDENCE else "shortlist"


def _after_ask(state: W1State) -> str:
    return "desk_handoff" if state.get("handoff_kind") else "await_answer"


def _after_shortlist(state: W1State) -> str:
    return "desk_handoff" if state.get("handoff_kind") else "pick"


def _after_book(state: W1State) -> str:
    return END if state.get("status") == "booked" else "shortlist"


# ---- nodes -------------------------------------------------------------------------------


class _Nodes:
    def __init__(self, deps: W1Deps):
        self.d = deps

    def intake(self, state: W1State) -> W1State:
        turns = state["turns"]
        with self.d.sessions() as session:
            dob = session.scalar(
                select(Patient.dob).where(Patient.patient_id == state["patient_id"])
            )
        age = state.get("request_age")
        if age is None and dob:
            age = _age(dob)
        return {
            "age_years": age,
            "language": state.get("language") or detect(" ".join(turns)),
            "clarify_count": 0,
        }

    def red_flag_rules(self, state: W1State) -> W1State:
        # A gate with no rules is a gate that did not run: fail closed rather than pass everyone
        if self.d.rules_enabled and not self.d.engine.concepts:
            return _to_desk("safety_unchecked", "Red-flag rules are not loaded", "desk", True)
        decision = self.d.engine.check(
            _joined(state), age_years=state.get("age_years"), enabled=self.d.rules_enabled
        )
        return {"fired": [_fired(f) for f in decision.fired]}

    def second_pass(self, state: W1State) -> W1State:
        """The safety check and the specialty match run side by side to meet the 4 s target. The
        match is only a stored answer until `match_specialty` reads it, which happens only after
        this check has passed."""
        if not self.d.rules_enabled:
            return {}
        with ThreadPoolExecutor(2) as pool:
            check = pool.submit(
                self._ask_model,
                prompts.SECOND_PASS_TASK,
                prompts.SECOND_PASS_SYSTEM,
                RedFlagSecondPass,
                state,
            )
            match = None
            if not asks_for_advice(_joined(state)):
                match = pool.submit(
                    self._ask_model,
                    prompts.MATCH_TASK,
                    prompts.MATCH_SYSTEM,
                    SpecialtyMatch,
                    state,
                )
        try:
            result = check.result()
        except ModelError as e:
            return _to_desk(
                "safety_unchecked",
                f"Model safety check did not complete ({type(e).__name__}); not yet ruled out as "
                "an emergency",
                "desk",
                True,
            )
        flags = result.output.add_flags
        if flags:
            return {
                "fired": [
                    {"rule": f"model:{f}", "label": result.output.reason, "kind": "model"}
                    for f in flags
                ]
            }
        return {"early_match": _stored_match(match)}

    def er_handoff(self, state: W1State) -> W1State:
        fired = state["fired"]
        codes = [f["rule"] for f in fired][:10]
        with self.d.sessions.begin() as session:
            ticket = desk.open_ticket(
                session,
                kind="er",
                reason="; ".join(dict.fromkeys(f["label"] for f in fired))[:500],
                reason_codes=codes,
                patient_id=state["patient_id"],
                patient_text=_joined(state),
                thread_id=state["thread_id"],
                trace_id=state["trace_id"],
            )
        name = "self_harm" if any("self_harm" in c for c in codes) else "emergency"
        return {
            "status": "emergency",
            "message": msg.message(name, state["language"]),
            "ticket_id": str(ticket),
        }

    def match_specialty(self, state: W1State) -> W1State:
        if asks_for_advice(_joined(state)):
            return _to_desk("advice_request", "Patient asked for a diagnosis or dose", "advice")
        stored = state.get("early_match")
        if stored and stored.get("error"):
            return _to_desk(
                "model_failure", f"Specialty match failed ({stored['error']})", "desk", True
            )
        if stored:
            match = SpecialtyMatch.model_validate(stored["match"])
        else:
            try:
                match = self._ask_model(
                    prompts.MATCH_TASK, prompts.MATCH_SYSTEM, SpecialtyMatch, state
                ).output
            except ModelError as e:
                return _to_desk(
                    "model_failure", f"Specialty match failed ({type(e).__name__})", "desk", True
                )
        if match.wants_diagnosis_or_dose:
            return _to_desk("advice_request", "Patient asked for a diagnosis or dose", "advice")
        with self.d.sessions() as session:
            name = session.scalar(
                select(Specialty.name).where(Specialty.specialty_id == match.specialty_id)
            )
        if name is None:
            return _to_desk(
                "model_failure", f"Model chose unknown specialty {match.specialty_id}", "desk", True
            )
        if match.specialty_id == EMERGENCY_MEDICINE:
            # The model can add an emergency; it has no way to book into one
            return {
                "fired": [
                    {
                        "rule": "model:emergency_medicine",
                        "label": "Model chose Emergency Medicine",
                        "kind": "model",
                    }
                ]
            }
        low = match.confidence < LOW_CONFIDENCE
        if low and state.get("clarify_count", 0) >= 1:
            return _to_desk(
                "low_confidence", "Still unsure of the specialty after one question", "desk"
            )
        return {
            "specialty_id": match.specialty_id,
            "specialty_name": name,
            "alternative": match.alternative,
            "confidence": match.confidence,
        }

    def ask(self, state: W1State) -> W1State:
        try:
            result = self._ask_model(
                prompts.CLARIFY_TASK,
                prompts.CLARIFY_SYSTEM,
                ClarifyQuestion,
                state,
                suffix=f"\nLanguage to write in: {state['language']}",
            )
        except ModelError as e:
            return _to_desk(
                "model_failure", f"Clarifying question failed ({type(e).__name__})", "desk", True
            )
        question = result.output.question
        if sounds_clinical(question):
            return _to_desk(
                "low_confidence", "Clarifying question failed the clinical wording check", "desk"
            )
        return {"question": question, "clarify_count": state.get("clarify_count", 0) + 1}

    def await_answer(self, state: W1State) -> W1State:
        answer = interrupt({"kind": "clarify", "question": state["question"]})
        return {"turns": [*state["turns"], answer["answer"]], "trace_id": answer["trace_id"]}

    def desk_handoff(self, state: W1State) -> W1State:
        with self.d.sessions.begin() as session:
            ticket = desk.open_ticket(
                session,
                kind=state["handoff_kind"],
                reason=state["handoff_reason"],
                reason_codes=[state["handoff_kind"]],
                patient_id=state["patient_id"],
                patient_text=_joined(state),
                thread_id=state["thread_id"],
                trace_id=state["trace_id"],
            )
        return {
            "status": "handed_to_desk",
            "message": msg.message(state["handoff_message"], state["language"]),
            "ticket_id": str(ticket),
        }

    def shortlist(self, state: W1State) -> W1State:
        with self.d.sessions() as session:
            found = service.search_doctors(
                session, state["specialty_id"], language=_doctor_language(state["language"])
            )
        if not found:
            return _to_desk(
                "no_availability", f"No free block in {state['specialty_name']}", "desk"
            )
        return {"candidates": [vars(c) for c in found]}

    def pick(self, state: W1State) -> W1State:
        choice = interrupt({"kind": "pick", "candidates": state["candidates"]})
        return {
            "slot_id": choice["slot_id"],
            "book_key": choice["book_key"],
            "trace_id": choice["trace_id"],
        }

    def book(self, state: W1State) -> W1State:
        chosen = next(c for c in state["candidates"] if c["slot_id"] == state["slot_id"])
        try:
            with self.d.sessions.begin() as session:
                r = service.reserve_slot(
                    session,
                    slot_id=state["slot_id"],
                    patient_id=state["patient_id"],
                    idem_key=state["book_key"],
                    booked_by="assistant",
                )
                times = msg.block_times(r.block_start, r.block_end, get_settings().timezone)
                doctor = session.scalar(
                    select(Doctor.name).where(Doctor.doctor_id == chosen["doctor_id"])
                )
                variables = {
                    "token": r.token_no,
                    "doctor": doctor,
                    "clinic": chosen["clinic"],
                    **times,
                }
                if not r.replayed:
                    desk.send_sms(
                        session,
                        patient_id=state["patient_id"],
                        template="booking_confirmed",
                        variables=variables,
                        appt_id=r.appt_id,
                        trace_id=state["trace_id"],
                    )
                    desk.open_ticket(
                        session,
                        kind="ai_booking",
                        reason=f"Assistant booked {state['specialty_name']} with {doctor}, "
                        f"token {r.token_no}",
                        reason_codes=[state["specialty_id"]],
                        patient_id=state["patient_id"],
                        appt_id=r.appt_id,
                        slot_id=r.slot_id,
                        thread_id=state["thread_id"],
                        trace_id=state["trace_id"],
                    )
        except (service.BlockFull, service.BlockStarted, service.SlotNotFound):
            return {"notice": msg.message("block_taken", state["language"])}
        except service.AlreadyBooked:
            return {"notice": msg.message("already_booked", state["language"])}
        return {
            "status": "booked",
            "notice": None,
            "message": msg.message("booked", state["language"], **variables),
            "appointment": {
                "appt_id": str(r.appt_id),
                "block_start": r.block_start.isoformat(),
                "block_end": r.block_end.isoformat(),
                "token_no": r.token_no,
                "sms_sent": True,
            },
        }

    # Every model call in this graph: scrubbed by the gateway, schema-checked, metered, traced
    def _ask_model(self, task, system, schema, state: W1State, *, suffix: str = ""):
        with self.d.sessions() as session:
            patient = session.get(Patient, state["patient_id"])
            known = KnownIdentity.from_patient(patient) if patient else None
        prompt = prompts.wrap_patient_text(state["turns"], age_years=state.get("age_years"))
        return self.d.gateway.complete(
            task,
            system=system,
            prompt=prompt + suffix,
            schema=schema,
            trace_id=state["trace_id"],
            patient=known,
            timeout_s=MODEL_TIMEOUT_S,
        )


def book_key(patient_id: str, client_key: str) -> str:
    """The appointment's key, per patient: one patient's key can't touch another's booking."""
    return "w1:" + hashlib.sha256(f"{patient_id}:{client_key}".encode()).hexdigest()[:60]


def _stored_match(future) -> dict | None:
    if future is None:
        return None
    try:
        return {"match": future.result().output.model_dump()}
    except ModelError as e:
        return {"error": type(e).__name__}


def _to_desk(kind: str, reason: str, message: str, unavailable: bool = False) -> W1State:
    return {
        "handoff_kind": kind,
        "handoff_reason": reason,
        "handoff_message": message,
        "service_unavailable": unavailable,
    }


def _joined(state: W1State) -> str:
    return " . ".join(state["turns"])


def _fired(f) -> dict:
    return {"rule": f.rule_id, "label": f.label, "kind": f.kind}


def _age(dob: date) -> int:
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _doctor_language(language: str) -> str:
    return "en" if language == "en" else "hi"
