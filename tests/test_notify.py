import pytest
from sqlalchemy import select

from sahyog.db import get_sessionmaker
from sahyog.models import Patient, SmsOutbox
from sahyog.notify import NoSender, SyntheticRecipient, deliver


class Recorder:
    def __init__(self):
        self.sent = []

    def send(self, phone, template, vars):
        self.sent.append(phone)


def _patient():
    with get_sessionmaker()() as session:
        return session.scalar(select(Patient).limit(1))


def test_a_synthetic_patient_is_never_contacted():
    patient = _patient()
    assert patient.synthetic
    sender = Recorder()
    sms = SmsOutbox(patient_id=patient.patient_id, template="booked", vars={}, trace_id="t")
    with pytest.raises(SyntheticRecipient):
        deliver(sms, patient, sender)
    assert not sender.sent


def test_without_an_adapter_nothing_is_sent():
    patient = _patient()
    patient.synthetic = False  # in memory only, to reach the next check
    sms = SmsOutbox(patient_id=patient.patient_id, template="booked", vars={}, trace_id="t")
    with pytest.raises(NoSender):
        deliver(sms, patient)


def test_seeded_patients_have_a_devanagari_name():
    patient = _patient()
    assert patient.name_local and any("\u0900" <= ch <= "\u097f" for ch in patient.name_local)
    assert "सम्मानात्मक" not in patient.name_local and "माननीय" not in patient.name_local
