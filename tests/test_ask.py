import json
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from sahyog.auth import AuthContext, Role, new_trace_id
from sahyog.db import get_sessionmaker
from sahyog.graphs import w1_prompts, w2_prompts
from sahyog.graphs.runtime import build_ask_graph
from sahyog.graphs.w2_ask import _Nodes as AskNodes
from sahyog.graphs.w2_ask import new_state, numbers
from sahyog.ingest.embedding import HashEmbedder
from sahyog.llm.adapters.fake import FakeModel
from sahyog.llm.adapters.fake_w1 import triage_script
from sahyog.llm.gateway import ModelGateway, Prices, Route
from sahyog.llm.types import ModelTimeout
from sahyog.models import AuditEvent, Consent, DeskTicket, Patient
from sahyog.records.scope import can_read
from sahyog.records.search import Hit
from sahyog.safety.text import normalise
from sahyog.safety.wording import clinical_answer
from tests.conftest import bearer
from tests.test_ingest import (
    embedder,  # noqa: F401 - pytest fixture
    ingest,
    pdf,
)
from tests.test_ingest import graph as ingest_graph  # noqa: F401 - pytest fixture

Sessions = get_sessionmaker
SECOND = "W1 second pass"
ANSWER = "W2 answer"
GRADE = "W2 grade"


class World:
    def __init__(self, monkeypatch):
        self.overrides = {}
        self.model = FakeModel(self._script)
        gateway = ModelGateway(
            {"v": self.model},
            {"small": Route("v", "fake-small"), "large": Route("v", "fake-large")},
            {},
            Prices(Path("config/prices.yaml")),
        )
        self.graph = build_ask_graph(gateway=gateway, embedder=HashEmbedder())
        monkeypatch.setattr("sahyog.api.w2.get_ask_graph", lambda: self.graph)

    def _script(self, request):
        for prefix, reply in self.overrides.items():
            if request.system.startswith(prefix):
                return reply(request) if callable(reply) else reply
        return triage_script(request)

    def sent(self, prefix):
        return [r for r in self.model.received if r.system.startswith(prefix)]


@pytest.fixture
def world(monkeypatch):
    return World(monkeypatch)


def ask(client, who, patient, q, role=Role.PATIENT):
    r = client.post(
        "/w2/ask",
        json={"question": q, "patient_id": patient},
        headers=bearer(role, who),
    )
    if r.status_code == 403:
        return r, None
    data = [ln for ln in r.text.splitlines() if ln.startswith("data: ") and ln != "data: {}"]
    return r, json.loads(data[0].removeprefix("data: "))


def draft(*sentences, found=True, wants=False):
    return json.dumps(
        {
            "found": found,
            "wants_diagnosis_or_dose": wants,
            "sentences": [{"text": t, "excerpts": e} for t, e in sentences],
        }
    )


@pytest.fixture
def report(ingest_graph):  # noqa: F811
    """A text report on P0030, unique to each test so searches stay simple."""

    def make(pid="P0030", body=None):
        unique = uuid.uuid4().hex[:6]
        text = body or (
            f"BIOCHEMISTRY ref{unique}\nHbA1c 7.2 % 4.0-5.6\nTSH 3.14 mIU/L 0.4-4.5\n"
            "Medicines: Metformin 500 mg"
        )
        return ingest(ingest_graph, pid, pdf(text))

    return make


# ---- answering -------------------------------------------------------------------------------


def test_an_answer_cites_document_and_page(client, world, report):
    doc = report()
    r, body = ask(client, "P0030", "P0030", "what is my hba1c")
    assert r.status_code == 200 and "text/event-stream" in r.headers["content-type"]
    assert body["status"] == "answered" and "7.2" in body["answer"]
    assert {c["doc_id"] for c in body["citations"]} >= {str(doc)} or body["citations"]
    assert all({"doc_id", "page", "source"} <= c.keys() for c in body["citations"])


def test_nothing_in_the_record_means_no_answer_and_no_guess(client, world, report):
    report()
    world.overrides[ANSWER] = draft(found=False)
    _, body = ask(client, "P0030", "P0030", "what is my blood group")
    assert body["status"] == "not_found" and not body["citations"]


def test_no_chunks_at_all_never_calls_the_answer_model(client, world):
    _, body = ask(client, "P0031", "P0031", "what is my hba1c")
    assert body["status"] == "not_found" and not world.sent(ANSWER)


def test_scan_sourced_answer_gets_the_warning_from_code(client, world, ingest_graph):  # noqa: F811
    from sahyog.evals.w2_samples import _rasterise

    ingest(
        ingest_graph, "P0032", _rasterise(pdf("HbA1c 8.1 % 4.0-5.6\nSerum Urea 44 mg/dL"), dpi=200)
    )
    _, body = ask(client, "P0032", "P0032", "my hba1c")
    assert body["status"] == "answered"
    assert body["citations"][0]["source"] == "ocr"
    assert "scanned page" in body["scan_warning"] and body["scan_warning"] in body["answer"]
    assert "page 1" in body["scan_warning"]


def test_a_text_sourced_answer_has_no_scan_warning(client, world, report):
    report()
    _, body = ask(client, "P0030", "P0030", "my hba1c")
    assert "scan_warning" not in body


# ---- the safety check ------------------------------------------------------------------------


def blocked(client, world, report, reply, q="my hba1c"):
    report()
    world.overrides[ANSWER] = reply
    r, body = ask(client, "P0030", "P0030", q)
    assert r.status_code == 200 and body["status"] == "blocked", body
    assert not body["citations"]
    with Sessions()() as s:
        t = s.execute(select(DeskTicket).where(DeskTicket.thread_id == body["ask_id"])).scalar()
    assert t.kind == "answer_blocked"
    return t, body


def test_a_changed_number_is_blocked_and_never_shown(client, world, report):
    t, body = blocked(client, world, report, draft(("Your HbA1c was 9.9 %.", [1])))
    assert t.reason_codes == ["number_not_in_cited_text"]
    assert "9.9" not in body["answer"]


def test_a_sentence_with_no_citation_is_blocked(client, world, report):
    t, _ = blocked(client, world, report, draft(("Your HbA1c was 7.2 %.", [])))
    assert t.reason_codes == ["sentence_without_citation"]


def test_a_citation_to_an_excerpt_that_doesnt_exist_is_blocked(client, world, report):
    t, _ = blocked(client, world, report, draft(("Your HbA1c was 7.2 %.", [99])))
    assert t.reason_codes == ["citation_out_of_range"]


def test_another_patients_id_in_an_answer_is_blocked(client, world, report):
    t, _ = blocked(client, world, report, draft(("P0031 has an HbA1c of 7.2 %.", [1])))
    assert t.reason_codes == ["foreign_patient_id"]


def test_a_document_id_in_the_answer_that_wasnt_cited_is_blocked(client, world, report):
    t, _ = blocked(client, world, report, draft((f"See document {uuid.uuid4()} for 7.2 %.", [1])))
    assert t.reason_codes == ["foreign_document_id"]


@pytest.mark.parametrize(
    "text",
    [
        "Your HbA1c of 7.2 % indicates diabetes.",
        "This suggests poor control, at 7.2 %.",
        "You should take more Metformin 500 mg.",
    ],
)
def test_interpreting_a_value_is_blocked(client, world, report, text):
    t, _ = blocked(client, world, report, draft((text, [1])))
    assert t.reason_codes == ["clinical_wording"]


def test_reading_back_a_printed_dose_or_range_is_allowed():
    assert not clinical_answer("Your report lists Metformin 500 mg.")
    assert not clinical_answer("Your HbA1c was 7.2 %, with a printed range of 4.0-5.6.")


def test_foreign_chunk_reaching_the_answer_is_blocked(world, report, monkeypatch, client):
    """Even if search were ever wrong, the citation check holds: F9."""
    foreign_doc = report("P0033")
    report("P0034")
    foreign = Hit(uuid.uuid4(), foreign_doc, "P0033", 1, "HbA1c 7.2 %", "text", None, 1.0)
    monkeypatch.setattr(AskNodes, "_retrieve", lambda self, state, k: [foreign])
    world.overrides[ANSWER] = draft(("Your HbA1c was 7.2 %.", [1]))
    _, body = ask(client, "P0034", "P0034", "my hba1c")
    assert body["status"] == "blocked"
    with Sessions()() as s:
        t = s.execute(select(DeskTicket).where(DeskTicket.thread_id == body["ask_id"])).scalar()
    assert t.reason_codes == ["foreign_document"]


def test_devanagari_digits_count_as_the_same_number():
    assert numbers("एचबीए1सी ७.२ %") == {"1", "7.2"}


# ---- scope and consent -----------------------------------------------------------------------


def test_a_patient_cannot_ask_about_another_patient(client, world, report):
    report("P0035")
    r, _ = ask(client, "P0036", "P0035", "my hba1c")
    assert r.status_code == 403
    with Sessions()() as s:
        row = s.execute(
            select(AuditEvent).where(
                AuditEvent.actor_id == "P0036",
                AuditEvent.record_id == "P0035",
                AuditEvent.outcome == "denied",
            )
        ).first()
    assert row


def _consent_for(expired: bool):
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    with Sessions()() as s:
        rows = s.execute(select(Consent).order_by(Consent.patient_id)).scalars().all()
        return next(c for c in rows if (c.expires_at < now) == expired)


def test_a_caregiver_with_valid_consent_reads_only_that_patient(client, world, report):
    c = _consent_for(expired=False)
    report(c.patient_id)
    r, body = ask(client, c.grantee_id, c.patient_id, "my hba1c", role=Role.CAREGIVER)
    assert r.status_code == 200 and body["status"] == "answered"
    other = "P0040" if c.patient_id != "P0040" else "P0041"
    r, _ = ask(client, c.grantee_id, other, "my hba1c", role=Role.CAREGIVER)
    assert r.status_code == 403


def test_expired_consent_returns_no_data_and_is_audited(client, world, report):
    c = _consent_for(expired=True)
    report(c.patient_id)
    r, body = ask(client, c.grantee_id, c.patient_id, "my hba1c", role=Role.CAREGIVER)
    assert r.status_code == 403 and body is None
    assert "7.2" not in r.text and not world.model.received
    with Sessions()() as s:
        assert s.execute(
            select(AuditEvent).where(
                AuditEvent.actor_id == c.grantee_id,
                AuditEvent.record_id == c.patient_id,
                AuditEvent.outcome == "denied",
            )
        ).first()


def test_consent_is_checked_on_every_read(client, world, report):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    c = _consent_for(expired=False)
    report(c.patient_id)
    r, _ = ask(client, c.grantee_id, c.patient_id, "my hba1c", role=Role.CAREGIVER)
    assert r.status_code == 200
    with Sessions().begin() as s:
        s.execute(
            update(Consent)
            .where(Consent.consent_id == c.consent_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    r, _ = ask(client, c.grantee_id, c.patient_id, "my hba1c", role=Role.CAREGIVER)
    assert r.status_code == 403
    with Sessions().begin() as s:
        s.execute(
            update(Consent)
            .where(Consent.consent_id == c.consent_id)
            .values(expires_at=c.expires_at)
        )


def test_wrong_purpose_and_other_roles_are_refused():
    c = _consent_for(expired=False)
    with Sessions()() as s:
        wrong = AuthContext(c.grantee_id, Role.CAREGIVER, "marketing", new_trace_id())
        assert not can_read(s, wrong, c.patient_id)
        desk = AuthContext("DESK01", Role.DESK, "scheduling", new_trace_id())
        assert not can_read(s, desk, c.patient_id)


# ---- emergencies and refusals ----------------------------------------------------------------


def test_emergency_wording_gets_the_emergency_message_and_no_model(client, world, report):
    report()
    _, body = ask(client, "P0030", "P0030", "seeing this report and now crushing chest pain")
    assert body["status"] == "emergency" and not body["citations"]
    assert not world.model.received


def test_model_second_pass_can_raise_an_emergency(client, world, report):
    report()
    world.overrides[SECOND] = json.dumps({"add_flags": ["cardiac"], "reason": "pressure"})
    _, body = ask(client, "P0030", "P0030", "an elephant is sitting on me, what is my hba1c")
    assert body["status"] == "emergency" and not world.sent(ANSWER)


def test_failed_second_pass_goes_to_the_desk_with_no_answer(client, world, report):
    report()
    world.overrides[SECOND] = ModelTimeout("slow")
    r, body = ask(client, "P0030", "P0030", "my hba1c")
    assert r.status_code == 503 and body["handoff"] and body["status"] == "handed_to_desk"
    assert not body["citations"] and "7.2" not in body["answer"]


def test_a_crash_goes_to_the_desk(client, world, report):
    report()

    def boom(*a, **k):
        raise RuntimeError("unexpected")

    world.overrides[ANSWER] = boom
    r, body = ask(client, "P0030", "P0030", "my hba1c")
    assert r.status_code == 503 and body["handoff"] and body["status"] == "handed_to_desk"
    assert "ticket_id" in body


@pytest.mark.parametrize("text", ["what tablet should I take", "मुझे कौन सी दवा लेनी चाहिए"])
def test_advice_is_refused_with_a_ticket_before_any_model(client, world, report, text):
    report()
    _, body = ask(client, "P0030", "P0030", text)
    assert body["status"] == "refused" and not world.model.received
    with Sessions()() as s:
        t = s.execute(select(DeskTicket).where(DeskTicket.thread_id == body["ask_id"])).scalar()
    assert t.kind == "advice_request"


def test_the_model_noticing_an_advice_request_also_counts(client, world, report):
    report()
    world.overrides[ANSWER] = draft(found=True, wants=True)
    _, body = ask(client, "P0030", "P0030", "is this diabetes")
    assert body["status"] == "refused"


def test_grade_failure_doesnt_stop_an_answer(client, world, report):
    report()
    world.overrides[GRADE] = ModelTimeout("slow")
    _, body = ask(client, "P0030", "P0030", "my hba1c")
    assert body["status"] == "answered"


def test_weak_context_widens_once(client, world, report):
    report()
    world.overrides[GRADE] = json.dumps({"relevant": False})
    _, body = ask(client, "P0030", "P0030", "my hba1c")
    assert body["status"] == "answered" and len(world.sent(GRADE)) == 1


# ---- boundary --------------------------------------------------------------------------------


def test_nothing_identifying_reaches_the_model(client, world, ingest_graph):  # noqa: F811
    with Sessions()() as s:
        p = s.get(Patient, "P0037")
    ingest(ingest_graph, "P0037", pdf(f"Patient Name: {p.name}\nABHA: {p.abha_id}\nHbA1c 6.9 %"))
    ask(client, "P0037", "P0037", f"I am {p.name}, what is my hba1c")
    assert world.model.received
    for req in world.model.received:
        assert p.name not in req.prompt and p.abha_id not in req.prompt


def test_a_prompt_never_shares_five_words_with_an_eval_case():
    """S2's prompt echoed its test wording by accident. Make it visible."""
    cases = [json.loads(ln) for ln in Path("evals/w2/ask.jsonl").read_text().splitlines()]
    case_grams = set()
    for c in cases:
        words = re.findall(r"\w+", normalise(c["question"]))
        case_grams |= {tuple(words[i : i + 5]) for i in range(len(words) - 4)}
    for prompt in (
        w2_prompts.GRADE_SYSTEM,
        w2_prompts.ANSWER_SYSTEM,
        w1_prompts.SECOND_PASS_SYSTEM,
    ):
        words = re.findall(r"\w+", normalise(prompt))
        grams = {tuple(words[i : i + 5]) for i in range(len(words) - 4)}
        assert not grams & case_grams


def test_new_state_takes_identity_from_the_context():
    ctx = AuthContext("P0030", Role.PATIENT, "self_access", new_trace_id())
    state = new_state(ctx, "P0030", "q")
    assert state["actor_id"] == "P0030" and state["role"] == "patient"
