import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from sahyog.auth import Role, issue_token
from sahyog.db import get_sessionmaker
from sahyog.llm.adapters.fake import FakeModel, Sequence
from sahyog.llm.gateway import CircuitBreaker, ModelGateway, Prices, Route, build_gateway
from sahyog.llm.schemas import Ack
from sahyog.llm.types import ModelTimeout, ModelUnavailable
from sahyog.models import AuditEvent, Slot, TraceSpan
from sahyog.observability import cost_per_consultation, tiles, workflow_of

PRICES = Prices(Path("config/prices.yaml"))


def gateway(model, **kw):
    return ModelGateway({"v": model}, {"small": Route("v", "fake-small")}, {}, PRICES, **kw)


def call(gw, system="s"):
    return gw.complete("small", system=system, prompt="p", schema=Ack, trace_id=uuid.uuid4().hex)


def test_circuit_opens_after_repeated_failures_and_stops_calling_the_provider():
    model = FakeModel(Sequence(ModelUnavailable("down")))
    gw = gateway(model, breaker=CircuitBreaker(threshold=2, open_seconds=60))
    with pytest.raises(ModelUnavailable):
        call(gw)
    calls = len(model.received)
    with pytest.raises(ModelUnavailable, match="circuit open"):
        call(gw)
    assert len(model.received) == calls


def test_circuit_lets_a_trial_through_and_closes_on_success():
    model = FakeModel(Sequence(ModelTimeout("slow"), ModelTimeout("slow"), '{"received": true}'))
    gw = gateway(model, breaker=CircuitBreaker(threshold=2, open_seconds=0))
    with pytest.raises(ModelTimeout):
        call(gw)
    assert call(gw).output.received
    assert gw.breaker.allows("v")


def test_a_refusal_doesnt_count_against_the_provider():
    from sahyog.llm.types import ModelRefused

    breaker = CircuitBreaker(threshold=1, open_seconds=60)
    gw = gateway(FakeModel(Sequence(ModelRefused("no"))), breaker=breaker)
    with pytest.raises(ModelRefused):
        call(gw)
    assert breaker.allows("v")


def test_each_model_call_writes_a_span_with_no_prompt_text():
    gw = gateway(FakeModel('{"received": true}'), tracing=True)
    result = call(gw, "W2 answer. Secret system text")
    with get_sessionmaker()() as s:
        span = s.execute(
            select(TraceSpan).where(TraceSpan.trace_id == result.record.trace_id)
        ).scalar()
    assert span.workflow == "w2" and span.outcome == "ok" and span.input_tokens > 0
    assert "text" not in {c.name for c in TraceSpan.__table__.columns}


def test_a_trace_fault_never_stops_a_call(monkeypatch):
    monkeypatch.setattr("sahyog.observability.get_sessionmaker", lambda: None)
    assert call(gateway(FakeModel('{"received": true}'), tracing=True)).output.received


def test_workflow_names():
    assert workflow_of("W1 second pass. x") == ("safety", "W1 second pass")
    assert workflow_of("W3 draft. x")[0] == "w3"


def test_tiles_come_from_real_rows():
    gw = gateway(FakeModel('{"received": true}'), tracing=True)
    call(gw, "W1 specialty match. x")
    t = tiles()
    assert t["model_calls"] >= 1 and t["workflows"]["w1"]["calls"] >= 1


def test_cost_shows_its_formula_and_says_when_infrastructure_is_a_placeholder():
    cost = cost_per_consultation()
    assert "consultations" in cost["formula"] and cost["prices_as_of"]
    assert cost["infrastructure_prices_are_placeholders"] is True


def test_vendor_can_be_swapped_by_settings_alone():
    from sahyog.config import Settings

    gw = build_gateway(
        Settings(
            llm_provider="openrouter",
            openrouter_api_key="test-not-real",
            openrouter_large_model="google/gemini-2.5-flash",
        )
    )
    assert gw.routes["large"].model == "google/gemini-2.5-flash"


def test_health_reports_the_worker(client):
    assert client.get("/health").json()["worker"] in ("ok", "no heartbeat", "unknown")


# ---- MCP -------------------------------------------------------------------------------------


@pytest.fixture
def mcp_as(monkeypatch):
    from sahyog import mcp_server

    def use(role, who):
        monkeypatch.setenv("SAHYOG_TOKEN", issue_token(role, who))
        return mcp_server

    return use


def test_mcp_tools_are_listed():
    from sahyog.mcp_server import mcp

    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == {"search_doctors", "list_slots", "reserve_slot", "stock_lookup"}


def test_mcp_books_for_the_tokens_patient_only_and_audits(mcp_as):
    server = mcp_as(Role.PATIENT, "P0058")
    with get_sessionmaker()() as s:
        slot = s.execute(select(Slot).order_by(Slot.slot_id).offset(40).limit(1)).scalar()
    key = uuid.uuid4().hex
    first = server.reserve_slot(slot.slot_id, key)
    assert first == server.reserve_slot(slot.slot_id, key)
    with get_sessionmaker()() as s:
        assert s.execute(
            select(AuditEvent).where(
                AuditEvent.actor_id == "P0058", AuditEvent.action == "mcp:reserve"
            )
        ).first()


def test_mcp_refuses_the_wrong_role_and_a_bad_token(mcp_as, monkeypatch):
    server = mcp_as(Role.DOCTOR, "D0001")
    with pytest.raises(server.NotPermitted):
        server.reserve_slot("any", "key12345")
    server = mcp_as(Role.PATIENT, "P0001")
    with pytest.raises(server.NotPermitted):
        server.stock_lookup("Metformin", "500 mg", "C01")
    monkeypatch.setenv("SAHYOG_TOKEN", "not-a-token")
    with pytest.raises(Exception, match="(?i)segments|token|decode"):
        server.list_slots("D0001")
