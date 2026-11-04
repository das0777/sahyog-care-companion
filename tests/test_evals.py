import json
from pathlib import Path

from sahyog.db import get_sessionmaker
from sahyog.evals.egress import build_payloads, detect
from sahyog.llm.adapters.fake import FakeModel
from sahyog.llm.gateway import ModelGateway, Prices, Route
from sahyog.llm.schemas import SpecialtyMatch
from sahyog.llm.types import SchemaRejected
from sahyog.safety.deid import Scrubber


def payloads(n=40):
    with get_sessionmaker()() as session:
        return build_payloads(session, n=n)


def test_payloads_are_deterministic():
    assert [p.text for p in payloads()] == [p.text for p in payloads()]


def test_detector_finds_every_planted_identifier_in_raw_text():
    # The detector must see leaks when nothing is scrubbed, or a zero in the replay means nothing
    for p in payloads():
        kinds = {leak.kind.split()[0] for leak in detect(p, p.text)}
        assert {i.kind for i in p.planted} <= kinds | {"long"}, p.id


def test_scrubbed_payloads_have_no_leaks():
    scrubber = Scrubber()
    with get_sessionmaker()() as session:
        from sahyog.models import Patient
        from sahyog.safety.deid import KnownIdentity

        for p in payloads():
            known = KnownIdentity.from_patient(session.get(Patient, p.patient_id))
            assert detect(p, scrubber.scrub(p.text, patient=known).text) == [], p.id


def test_every_malformed_fixture_is_rejected():
    files = sorted(Path("evals/fixtures/malformed").glob("*.json"))
    assert len(files) >= 10
    for f in files:
        reply = json.loads(f.read_text())["reply"]
        gw = ModelGateway(
            {"v": FakeModel(reply)},
            {"small": Route("v", "fake-small")},
            {},
            Prices(Path("config/prices.yaml")),
        )
        try:
            gw.complete("small", system="s", prompt="p", schema=SpecialtyMatch, trace_id="t")
        except SchemaRejected:
            continue
        raise AssertionError(f"{f.name} was accepted")
