"""Offline W3 paths through the real graph on scripted replies, including a model that invents a
drug. Proves grounding and the signature, not how good a real model's drafts are."""

import json
import uuid
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import delete, func, select

from sahyog.db import get_sessionmaker
from sahyog.graphs.w3 import ScribeDeps, build_w3
from sahyog.llm.adapters.fake import FakeModel
from sahyog.llm.adapters.fake_w1 import triage_script
from sahyog.llm.gateway import ModelGateway, Prices, Route
from sahyog.models import (
    Appointment,
    ClinicalNote,
    Encounter,
    Patient,
    Prescription,
    Slot,
    SmsOutbox,
    StockReservation,
)
from sahyog.scheduling.service import AlreadyBooked, BlockFull, reserve_slot
from sahyog.scribe.stock import CsvStockAdapter


def _inventing(request):
    if request.system.startswith("W3 medicines"):
        return json.dumps(
            {
                "medicines": [
                    {"name": "Rosuvastatin", "dose": "40 mg", "span": "take rosuvastatin 40 mg"},
                    {"name": "statin", "dose": "", "span": "low dose statin"},
                    {"name": "Metformin", "dose": "500 mg", "span": "metformin 500 mg"},
                ]
            }
        )
    if request.system.startswith("W3 draft"):
        plan = [
            {"text": "Start a low dose statin", "quote": "Start a low dose statin"},
            {"text": "Rosuvastatin 40 mg", "quote": "Rosuvastatin 40 mg"},
            {"text": "Add warfarin 5 mg", "quote": "Start a low dose statin"},
        ]
        return json.dumps({"subjective": [], "objective": [], "assessment": [], "plan": plan})
    return triage_script(request)


def w3_paths(guardrails: bool) -> tuple[list[tuple], dict]:
    sessions = get_sessionmaker()
    vendor = FakeModel(_inventing, name="vendor")
    gateway = ModelGateway(
        {"vendor": vendor},
        {"small": Route("vendor", "fake-small"), "large": Route("vendor", "fake-large")},
        {},
        Prices(Path("config/prices.yaml")),
        scrub_enabled=guardrails,
    )
    graph = build_w3(
        ScribeDeps(gateway, CsvStockAdapter(Path("config/stock.csv")), sessions, guardrails),
        InMemorySaver(),
    )
    appt, encounter = _encounter(sessions)
    try:
        with sessions() as session:
            enc = session.get(Encounter, encounter)
            appointment = session.get(Appointment, enc.appt_id)
            patient = session.get(Patient, appointment.patient_id)
            slot = session.get(Slot, appointment.slot_id)
            name = patient.name
        transcript = (
            f"Doctor: {name} is a known diabetic. Start a low dose statin. "
            "Continue metformin 500 mg twice daily."
        )
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        graph.invoke(
            {
                "thread_id": "t",
                "encounter_id": str(encounter),
                "doctor_id": enc.doctor_id,
                "patient_id": patient.patient_id,
                "clinic_id": slot.clinic_id,
                "trace_id": uuid.uuid4().hex,
                "transcript": transcript,
            },
            config,
        )
        pause = [i.value for t in graph.get_state(config).tasks for i in t.interrupts][0]
        names = [m["name"].lower() for m in pause["medicines"]]
        plan = " ".join(line["text"].lower() for line in pause["soap"]["plan"])
        invented = sum(w in names or w in plan for w in ("rosuvastatin", "warfarin"))
        gap_kept = any("statin" in g["term"].lower() for g in pause["gaps"])
        flagged = all("stock" in m for m in pause["medicines"])
        with sessions() as session:
            before = session.scalar(
                select(func.count())
                .select_from(ClinicalNote)
                .where(ClinicalNote.encounter_id == encounter)
            )
        leaked = sum(name in r.prompt for r in vendor.received)
        graph.invoke(
            Command(
                resume={
                    "decision": "sign",
                    "edits": {"medicines": [{"name": "Metformin", "dose": "500 mg"}], "gaps": []},
                    "trace_id": uuid.uuid4().hex,
                }
            ),
            config,
        )
        with sessions() as session:
            after = session.scalar(
                select(func.count())
                .select_from(ClinicalNote)
                .where(ClinicalNote.encounter_id == encounter)
            )
        rows = [
            (
                "G3o",
                "Invented drugs surviving, on a model that invents",
                "0",
                str(invented),
                invented == 0,
            ),
            ("G4o", "Class without molecule stays a gap", "Yes", str(gap_kept), gap_kept),
            (
                "G7",
                "Notes stored before signing, then after",
                "0, then 1",
                f"{before}, then {after}",
                before == 0 and after == 1,
            ),
            ("G9o", "Every medicine carries a stock line", "Yes", str(flagged), flagged),
            (
                "G12",
                f"Patient name reaching the model ({len(vendor.received)} calls)",
                "0",
                str(leaked),
                leaked == 0,
            ),
        ]
        return rows, {}
    finally:
        with sessions.begin() as session:
            notes = list(
                session.scalars(
                    select(ClinicalNote.note_id).where(ClinicalNote.encounter_id == encounter)
                )
            )
            session.execute(delete(StockReservation).where(StockReservation.note_id.in_(notes)))
            session.execute(delete(Prescription).where(Prescription.note_id.in_(notes)))
            session.execute(delete(SmsOutbox).where(SmsOutbox.patient_id == patient.patient_id))
            # A signed note can't be deleted, by design: it stays on the eval's synthetic patient


def _encounter(sessions) -> tuple[uuid.UUID, uuid.UUID]:
    # A signed note can't be deleted, so each run needs a block this patient isn't in yet
    with sessions.begin() as session:
        slots = session.execute(select(Slot).order_by(Slot.starts_at.desc()).limit(200)).scalars()
        for slot in slots:
            try:
                r = reserve_slot(
                    session,
                    slot_id=slot.slot_id,
                    patient_id="P0998",
                    idem_key=f"eval-w3-{uuid.uuid4().hex}",
                    booked_by="eval",
                )
                break
            except (AlreadyBooked, BlockFull):
                continue
        else:
            raise RuntimeError("No free block left for the W3 eval: run make seed")
        encounter = Encounter(appt_id=r.appt_id, doctor_id=slot.doctor_id)
        session.add(encounter)
        session.flush()
        return r.appt_id, encounter.encounter_id
