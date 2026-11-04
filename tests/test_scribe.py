import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select, update

from sahyog.auth import Role
from sahyog.db import get_sessionmaker
from sahyog.graphs import w3_prompts
from sahyog.graphs.runtime import W1Runtime
from sahyog.graphs.w3 import ScribeDeps, build_w3
from sahyog.llm.adapters.fake import FakeModel
from sahyog.llm.adapters.fake_w1 import triage_script
from sahyog.llm.gateway import ModelGateway, Prices, Route
from sahyog.llm.types import ModelTimeout
from sahyog.models import (
    AuditEvent,
    ClinicalNote,
    Encounter,
    Prescription,
    ScribeJob,
    Slot,
    SmsOutbox,
    StockReservation,
)
from sahyog.safety.text import normalise
from sahyog.scheduling.service import reserve_slot
from sahyog.scribe import grounding, jobs
from sahyog.scribe.stock import CsvStockAdapter
from tests.conftest import bearer

Sessions = get_sessionmaker
DRAFT = "W3 draft"
MEDS = "W3 medicines"
STATIN = (
    "Doctor: Known diabetic, HbA1c 8.4 percent. Start a low dose statin. "
    "Continue metformin 500 mg twice daily."
)


@pytest.fixture
def stock_csv(tmp_path):
    path = tmp_path / "stock.csv"
    today = date.today()
    old = today - timedelta(days=30)
    path.write_text(
        "medicine_id,clinic_id,name,composition,qty,as_of\n"
        f"M1,C01,Metformin 500,Metformin 500 mg,240,{today}\n"
        f"M2,C01,Atorvastatin 10,Atorvastatin 10 mg,5,{today}\n"
        f"M3,C01,Amoxicillin 500,Amoxicillin 500 mg,0,{today}\n"
        f"M4,C01,Cetirizine 10,Cetirizine 10 mg,50,{old}\n"
    )
    return path


class World:
    def __init__(self, monkeypatch, stock_csv):
        self.overrides = {}
        self.model = FakeModel(self._script)
        gateway = ModelGateway(
            {"v": self.model},
            {"small": Route("v", "fake-small"), "large": Route("v", "fake-large")},
            {},
            Prices(Path("config/prices.yaml")),
        )
        deps = ScribeDeps(gateway, CsvStockAdapter(stock_csv), Sessions())
        self.graph = build_w3(deps, InMemorySaver())
        runtime = W1Runtime(self.graph, deps, None)
        monkeypatch.setattr("sahyog.api.w3.get_scribe_runtime", lambda: runtime)

    def _script(self, request):
        for prefix, reply in self.overrides.items():
            if request.system.startswith(prefix):
                return reply(request) if callable(reply) else reply
        return triage_script(request)

    def run_jobs(self):
        with Sessions().begin() as session:
            job = jobs.claim_scribe(session, lease_s=60)
        if job:
            jobs.run_scribe_job(self.graph, Sessions(), job)
        return job


@pytest.fixture
def world(monkeypatch, stock_csv):
    return World(monkeypatch, stock_csv)


def _setup(patient="P0020", offset=100):
    with Sessions().begin() as s:
        slot = s.execute(
            select(Slot)
            .where(Slot.clinic_id == "C01")
            .order_by(Slot.slot_id)
            .offset(offset - 100)
            .limit(1)
        ).scalar()
        r = reserve_slot(
            s,
            slot_id=slot.slot_id,
            patient_id=patient,
            idem_key=uuid.uuid4().hex,
            booked_by="test",
        )
    return r.appt_id, slot.doctor_id


def doc(client, doctor, path, **kw):
    return client.post(path, headers=bearer(Role.DOCTOR, doctor), **kw)


def start(client, world, text=STATIN, offset=100, patient="P0020"):
    appt, doctor = _setup(patient, offset)
    enc = doc(client, doctor, "/w3/encounters", json={"appt_id": str(appt)}).json()["encounter_id"]
    thread = doc(
        client, doctor, f"/w3/encounters/{enc}/transcript", json={"transcript": text}
    ).json()["thread_id"]
    assert world.run_jobs()
    draft = client.get(f"/w3/{thread}/draft", headers=bearer(Role.DOCTOR, doctor)).json()
    return doctor, enc, thread, draft


# ---- grounding -------------------------------------------------------------------------------


def test_segment_uses_labels_and_treats_unlabelled_speech_as_the_doctors():
    turns = grounding.segment("Patient: my head hurts. Doctor: Take rest.")
    assert [(t.speaker, t.text) for t in turns] == [
        ("patient", "my head hurts."),
        ("doctor", "Take rest."),
    ]
    assert grounding.segment("Take rest.")[0].speaker == "doctor"


def test_medicine_without_a_span_in_the_doctors_words_is_dropped():
    out = grounding.ground_medicines(
        [{"name": "Rosuvastatin", "dose": "40 mg", "span": "take rosuvastatin 40 mg"}],
        "Start a low dose statin.",
    )
    assert not out.medicines and out.dropped == ["Rosuvastatin"]


def test_a_medicine_only_the_patient_named_is_not_the_doctors():
    turns = grounding.segment("Patient: I take aspirin 75 mg. Doctor: Start paracetamol 500 mg.")
    doctor = grounding.doctors_words(turns)
    out = grounding.ground_medicines(
        [{"name": "Aspirin", "dose": "75 mg", "span": "aspirin 75 mg"}], doctor
    )
    assert out.dropped == ["Aspirin"]


def test_a_class_stays_a_gap_and_a_missing_dose_is_flagged():
    out = grounding.ground_medicines(
        [
            {"name": "statin", "dose": "", "span": "low dose statin"},
            {"name": "Metformin", "dose": "", "span": "continue metformin"},
            {"name": "beta blocker", "dose": "", "span": "add a beta blocker"},
        ],
        "Start a low dose statin, continue metformin and add a beta blocker.",
    )
    assert [g["term"] for g in out.gaps] == ["statin", "beta blocker"]
    assert "[molecule and dose not stated: doctor to specify]" in out.gaps[0]["text"]
    assert out.medicines[0]["dose_gap"] and "doctor to specify" in out.medicines[0]["text"]


def test_a_plural_or_qualified_class_is_still_a_gap():
    out = grounding.ground_medicines(
        [{"name": "oral steroids", "dose": "", "span": "a course of oral steroids"}],
        "Give a course of oral steroids.",
    )
    assert out.gaps and not out.medicines


def test_a_dose_the_doctor_never_said_is_removed():
    out = grounding.ground_medicines(
        [{"name": "Metformin", "dose": "1000 mg", "span": "continue metformin"}],
        "Please continue metformin.",
    )
    assert out.medicines[0]["dose"] == "" and out.medicines[0]["dose_gap"]


def test_a_plan_line_naming_an_unsaid_drug_or_number_is_cleaned():
    text, removed = grounding.clean_plan_line("Add warfarin 5 mg", "Start a low dose statin.")
    assert "warfarin" not in text.lower() and "5" not in text and {"warfarin", "5"} <= set(removed)
    same, none = grounding.clean_plan_line("Metformin 500 mg", "metformin 500 mg daily")
    assert same == "Metformin 500 mg" and not none


# ---- stock -----------------------------------------------------------------------------------


def test_every_status_and_age(stock_csv):
    s = CsvStockAdapter(stock_csv)
    assert s.lookup("Metformin", "500 mg", "C01").status == "in_stock"
    assert s.lookup("Atorvastatin", "10 mg", "C01").status == "low"
    assert s.lookup("Amoxicillin", "500 mg", "C01").status == "out"
    assert s.lookup("Warfarin", "5 mg", "C01").status == "unknown"
    old = s.lookup("Cetirizine", "10 mg", "C01")
    assert old.stale and old.age_days == 30


def test_a_different_strength_is_unknown_not_in_stock(stock_csv):
    assert CsvStockAdapter(stock_csv).lookup("Atorvastatin", "20 mg", "C01").status == "unknown"


def test_a_missing_file_is_unknown(tmp_path):
    assert CsvStockAdapter(tmp_path / "no.csv").lookup("x", "", "C01").status == "unknown"


# ---- the whole flow --------------------------------------------------------------------------


def test_dictation_becomes_a_draft_and_nothing_is_stored_before_signing(client, world):
    doctor, enc, thread, draft = start(client, world)
    assert draft["status"] == "review"
    assert draft["soap"]["plan"] and all(ln["quote"] for ln in draft["soap"]["plan"])
    assert [g["term"] for g in draft["gaps"]] == ["statin"]
    metformin = next(m for m in draft["medicines"] if m["name"].lower() == "metformin")
    assert metformin["stock"]["status"] == "in_stock" and metformin["stock"]["age_days"] == 0
    with Sessions()() as s:
        assert not s.execute(
            select(ClinicalNote).where(ClinicalNote.encounter_id == uuid.UUID(enc))
        ).first()


def test_signing_refuses_an_open_gap(client, world):
    doctor, _, thread, _ = start(client, world, offset=101, patient="P0021")
    r = doc(client, doctor, f"/w3/{thread}/resume", json={"decision": "sign"})
    assert r.status_code == 422 and "statin" in json.dumps(r.json())


def test_sign_with_the_gap_filled_stores_note_history_rx_stock_sms_and_audit(client, world):
    doctor, enc, thread, _ = start(client, world, offset=102, patient="P0022")
    edits = {
        "gaps": [],
        "medicines": [
            {"name": "Atorvastatin", "dose": "10 mg"},
            {"name": "Metformin", "dose": "500 mg"},
        ],
    }
    r = doc(client, doctor, f"/w3/{thread}/resume", json={"decision": "sign", "edits": edits})
    assert r.status_code == 200 and r.json()["status"] == "signed"
    note_id = uuid.UUID(r.json()["note_id"])
    with Sessions()() as s:
        note = s.get(ClinicalNote, note_id)
        rx = list(s.execute(select(Prescription).where(Prescription.note_id == note_id)).scalars())
        held = list(
            s.execute(select(StockReservation).where(StockReservation.note_id == note_id)).scalars()
        )
        sms = s.execute(select(SmsOutbox).where(SmsOutbox.template == "note_signed")).first()
        signed = s.execute(
            select(AuditEvent).where(
                AuditEvent.record_id == str(note_id), AuditEvent.action == "sign"
            )
        ).first()
    assert note.signed_at and len(note.hash) == 64 and note.edit_history[-1]["decision"] == "sign"
    assert {x.medicine_id for x in rx} == {"M1", "M2"} and len(held) == 2
    assert sms and signed
    assert note.soap_json["medicines"][0]["stock"]["status"] == "low"


def test_a_signed_note_cannot_change(client, world):
    doctor, enc, thread, _ = start(client, world, "Doctor: Rest for two days.", 103, "P0023")
    r = doc(client, doctor, f"/w3/{thread}/resume", json={"decision": "sign"})
    note_id = uuid.UUID(r.json()["note_id"])
    again = doc(client, doctor, f"/w3/{thread}/resume", json={"decision": "sign"})
    assert again.status_code == 423
    with Sessions()() as s, pytest.raises(Exception, match="signed"):
        s.execute(update(ClinicalNote).where(ClinicalNote.note_id == note_id).values(soap_json={}))
        s.commit()


def test_reject_redrafts_with_comments_and_nothing_is_stored(client, world):
    doctor, enc, thread, _ = start(client, world, offset=104, patient="P0024")
    empty = doc(client, doctor, f"/w3/{thread}/resume", json={"decision": "reject"})
    assert empty.status_code == 422
    r = doc(
        client,
        doctor,
        f"/w3/{thread}/resume",
        json={"decision": "reject", "comments": "Atorvastatin 10 mg is what I meant"},
    )
    assert r.status_code == 200 and r.json()["status"] == "review"
    assert "Atorvastatin 10 mg" in world.model.received[-1].prompt
    with Sessions()() as s:
        assert not s.execute(
            select(ClinicalNote).where(ClinicalNote.encounter_id == uuid.UUID(enc))
        ).first()


def test_edit_re_runs_stock(client, world):
    doctor, _, thread, _ = start(client, world, offset=105, patient="P0025")
    r = doc(
        client,
        doctor,
        f"/w3/{thread}/resume",
        json={
            "decision": "edit",
            "edits": {"gaps": [], "medicines": [{"name": "Amoxicillin", "dose": "500 mg"}]},
        },
    )
    assert r.json()["medicines"][0]["stock"]["status"] == "out"


def test_invented_drug_from_the_model_never_reaches_the_doctor(client, world):
    world.overrides[MEDS] = json.dumps(
        {
            "medicines": [
                {"name": "Rosuvastatin", "dose": "40 mg", "span": "take rosuvastatin 40 mg"},
                {"name": "statin", "dose": "", "span": "low dose statin"},
            ]
        }
    )
    world.overrides[DRAFT] = json.dumps(
        {
            "subjective": [],
            "objective": [],
            "assessment": [{"text": "Heart failure", "quote": "patient has heart failure"}],
            "plan": [{"text": "Add warfarin 5 mg", "quote": "Start a low dose statin."}],
        }
    )
    _, _, _, draft = start(client, world, offset=106, patient="P0026")
    assert not draft["medicines"] and draft["gaps"][0]["term"] == "statin"
    assert not draft["soap"]["assessment"]
    plan = draft["soap"]["plan"][0]["text"]
    # The line added a drug and a dose its quote doesn't hold, so it becomes the doctor's words
    assert "warfarin" not in plan.lower() and plan == "Start a low dose statin."
    assert len(draft["flags"]) >= 3


def test_a_model_failure_returns_the_job_to_the_queue(client, world):
    world.overrides[DRAFT] = ModelTimeout("slow")
    doctor, _, thread, draft = start(client, world, offset=107, patient="P0027")
    assert draft["status"] == "queued"
    with Sessions()() as s:
        job = s.execute(select(ScribeJob).where(ScribeJob.thread_id == thread)).scalar()
    assert job.attempts == 1
    world.overrides.pop(DRAFT)
    world.run_jobs()
    done = client.get(f"/w3/{thread}/draft", headers=bearer(Role.DOCTOR, doctor)).json()
    assert done["status"] == "review"


# ---- access ----------------------------------------------------------------------------------


def test_only_the_owning_doctor_can_act_and_refusals_are_audited(client, world):
    doctor, enc, thread, _ = start(client, world, offset=108, patient="P0028")
    other = "D0999" if doctor != "D0999" else "D0998"
    assert doc(client, other, f"/w3/{thread}/resume", json={"decision": "sign"}).status_code == 404
    assert client.get(f"/w3/{thread}/draft", headers=bearer(Role.DOCTOR, other)).status_code == 404
    assert (
        doc(client, other, f"/w3/encounters/{enc}/transcript", json={"transcript": "hello doctor"})
    ).status_code == 404
    patient = client.get(f"/w3/{thread}/draft", headers=bearer(Role.PATIENT, "P0028"))
    assert patient.status_code == 403
    with Sessions()() as s:
        denied = s.execute(
            select(AuditEvent).where(AuditEvent.actor_id == other, AuditEvent.outcome == "denied")
        ).all()
    assert len(denied) >= 3


def test_nothing_identifying_reaches_the_model(client, world):
    from sahyog.models import Patient

    with Sessions()() as s:
        p = s.get(Patient, "P0029")
    start(client, world, f"Doctor: {p.name}, phone {p.phone}. Rest for two days.", 109, "P0029")
    assert world.model.received
    for r in world.model.received:
        assert p.name not in r.prompt and p.phone.replace("+91 ", "") not in r.prompt


# ---- audio retention -------------------------------------------------------------------------


def test_audio_older_than_a_day_is_deleted_and_audited(monkeypatch):
    appt, doctor = _setup("P0030", 110)
    removed = []

    class Store:
        def remove_object(self, bucket, uri):
            removed.append(uri)

    monkeypatch.setattr(jobs, "get_minio", lambda: Store())
    with Sessions().begin() as s:
        e = Encounter(
            appt_id=appt,
            doctor_id=doctor,
            audio_uri="encounters/x.m4a",
            started_at=datetime.now(UTC) - timedelta(hours=23, minutes=30),
        )
        s.add(e)
        s.flush()
        eid = e.encounter_id
    assert jobs.purge_audio(Sessions()) >= 1
    assert "encounters/x.m4a" in removed
    with Sessions()() as s:
        assert s.get(Encounter, eid).audio_deleted_at
        assert s.execute(
            select(AuditEvent).where(
                AuditEvent.record_id == str(eid), AuditEvent.action == "audio:delete"
            )
        ).first()


def test_a_prompt_never_shares_five_words_with_an_eval_case():
    cases = [json.loads(ln) for ln in Path("evals/w3/golden.jsonl").read_text().splitlines()]
    grams = set()
    for c in cases:
        w = re.findall(r"\w+", normalise(c["transcript"]))
        grams |= {tuple(w[i : i + 5]) for i in range(len(w) - 4)}
    for prompt in (w3_prompts.DRAFT_SYSTEM, w3_prompts.MEDS_SYSTEM):
        w = re.findall(r"\w+", normalise(prompt))
        assert not {tuple(w[i : i + 5]) for i in range(len(w) - 4)} & grams


# ---- from the S5 review: grounding a medicine to what the doctor said about it -----------------


def _one(name, dose, doctor, span=None):
    out = grounding.ground_medicines([{"name": name, "dose": dose, "span": span or doctor}], doctor)
    return out


def test_a_dose_must_sit_beside_its_own_medicine():
    out = _one("Amlodipine", "5 mg", "Start amlodipine 25 mg once daily.")
    assert out.medicines[0]["dose_gap"]
    out = _one("Atorvastatin", "50 mg", "Atorvastatin daily. Metformin 250 mg twice.")
    assert out.medicines[0]["dose_gap"]
    out = _one("Amlodipine", "25 mg once daily", "Start amlodipine 25 mg once daily.")
    assert out.medicines[0]["dose"] == "25 mg once daily"


def test_a_route_or_frequency_not_said_is_a_gap():
    out = _one("Ceftriaxone", "250 mg IV every 4 hours", "Give ceftriaxone 250 mg.")
    assert out.medicines[0]["dose_gap"]


def test_a_similar_or_misspelled_name_is_not_the_doctors():
    assert _one("Valsartan", "50 mg", "Continue losartan 50 mg.").dropped == ["Valsartan"]
    assert _one("Amiodipine", "5 mg", "Start amlodipine 5 mg.").dropped == ["Amiodipine"]


@pytest.mark.parametrize(
    "doctor", ["Do not give metformin 500 mg.", "Stop aspirin 75 mg.", "No metformin 500 mg now."]
)
def test_a_negated_medicine_is_not_prescribed(doctor):
    """Not prescribed, and not silently dropped either: the doctor confirms or removes it."""
    name = "Aspirin" if "aspirin" in doctor else "Metformin"
    out = _one(name, "500 mg" if name == "Metformin" else "75 mg", doctor)
    assert not out.medicines and out.gaps[0]["term"] == name


@pytest.mark.parametrize(
    ("text", "quote", "strict"),
    [
        ("Start apixaban 5 mg", "Start a low dose statin", True),
        ("Ecosprin 75", "continue the blood thinner", True),
        ("Metformin fifty mg", "metformin as before", True),
        ("BP 150/90", "BP was high", False),
    ],
)
def test_a_soap_line_cant_add_to_its_quote(text, quote, strict):
    assert grounding.unfaithful(text, quote, strict=strict)


def test_a_soap_line_that_restates_its_quote_is_kept():
    assert not grounding.unfaithful(
        "Continue metformin 500 mg twice daily",
        "continue metformin 500 mg twice daily",
        strict=True,
    )


def test_an_edited_medicine_without_a_dose_blocks_the_signature():
    from sahyog.graphs.w3 import unresolved

    edits = {"medicines": [{"name": "Atorvastatin", "dose": ""}]}
    assert unresolved({"gaps": [], "medicines": []}, edits) == ["Atorvastatin: no dose"]


def test_editing_medicines_doesnt_clear_an_open_gap():
    from sahyog.graphs.w3 import unresolved

    state = {"gaps": [{"text": "statin [molecule and dose not stated]"}], "medicines": []}
    edits = {"medicines": [{"name": "Metformin", "dose": "500 mg"}]}
    assert unresolved(state, edits) == ["statin [molecule and dose not stated]"]


# ---- from the S5 re-review ---------------------------------------------------------------------

DICTATION = "50 year old man, a known diabetic. Continue metformin 500 mg twice daily."


def test_a_quote_must_be_the_doctors_exact_words():
    assert grounding.quoted("known diabetic", DICTATION)
    assert not grounding.quoted("non diabetic", DICTATION)
    assert not grounding.quoted("stop metformin", "Please start metformin 500 mg.")


def test_a_line_cant_borrow_a_number_or_add_a_negation():
    assert grounding.unfaithful(
        "Continue metformin 50 mg", "Continue metformin 500 mg", strict=True
    )
    assert grounding.unfaithful("Non diabetic", "a known diabetic", strict=False)
    assert grounding.unfaithful("Patient denies chest pain", "patient has chest pain", strict=False)


def test_a_dose_window_stops_at_an_unlisted_drug_or_a_new_clause():
    out = _one("Amlodipine", "10 mg", "Start amlodipine 5 mg and cilnidipine 10 mg.")
    assert out.medicines[0]["dose_gap"]


@pytest.mark.parametrize(
    "doctor",
    [
        "Metformin 500 mg is not needed anymore.",
        "Warfarin 5 mg should be avoided.",
        # From the S5 re-review 2
        "Metformin 500 mg, do not take it.",
        "Aspirin 75 mg, don't continue.",
        "Metformin 500 mg mat lena.",
    ],
)
def test_a_negation_anywhere_in_the_sentence_makes_the_doctor_confirm(doctor):
    name = next(n for n in ("Warfarin", "Aspirin", "Metformin") if n in doctor)
    out = _one(name, "500 mg", doctor)
    assert not out.medicines and out.gaps[0]["term"] == name


@pytest.mark.parametrize(
    ("name", "dose", "doctor"),
    [
        ("Metformin", "500 mg", "No change, continue metformin 500 mg."),
        ("Telmisartan", "40 mg", "Continue telmisartan 40 mg, avoid salt."),
        ("Paracetamol", "650 mg", "Patient has no fever so give paracetamol 650 mg."),
    ],
)
def test_a_real_prescription_near_a_negation_is_kept_for_the_doctor(name, dose, doctor):
    """Not dropped as unsaid: kept as a gap the doctor confirms in one step."""
    out = _one(name, dose, doctor)
    assert name not in out.dropped and out.gaps[0]["term"] == name


def test_a_prescription_with_no_negation_is_kept_with_its_dose():
    out = _one("Telmisartan", "40 mg", "Stop amlodipine and start telmisartan 40 mg.")
    assert name_kept(out, "Telmisartan") or out.gaps  # its sentence holds "stop": doctor confirms
    out = _one("Metformin", "500 mg twice daily", "Metformin 500 mg, twice daily.")
    assert out.medicines[0]["dose"] == "500 mg twice daily"


def name_kept(out, name):
    return any(m["name"] == name for m in out.medicines)


def test_unit_spacing_doesnt_matter():
    assert grounding.quoted("start amlodipine 5 mg", "Start amlodipine 5mg daily.")
    out = _one("Amlodipine", "5 mg", "Start amlodipine 5mg daily.", span="start amlodipine 5 mg")
    assert out.medicines[0]["dose"] == "5 mg"


@pytest.mark.parametrize(
    ("text", "quote"),
    [
        ("Start metformin 500 mg", "do not start metformin 500 mg"),
        ("Chest pain present", "no chest pain"),
    ],
)
def test_a_line_cant_drop_a_negation_its_quote_holds(text, quote):
    assert grounding.unfaithful(text, quote, strict=True)


def test_number_words_and_brands_are_whole_words():
    assert not grounding.unfaithful("seventy kg", "weight seventy kg", strict=False)
    assert grounding.unfaithful("seven days", "for seventy days", strict=False)
    assert grounding.unfaithful("forty-five mg", "as advised", strict=False)
    assert grounding.unfaithful("Glycomet 500 mg", "metformin 500 mg", strict=True)
    assert grounding.unfaithful("take dolo 650", "take paracetamol 650", strict=True)
