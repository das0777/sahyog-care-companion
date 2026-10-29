import ast
import json
from pathlib import Path

import httpx
import httpx2
import pytest

from sahyog.llm.adapters.anthropic import AnthropicModel
from sahyog.llm.adapters.fake import FakeModel, Sequence
from sahyog.llm.adapters.ollama import OllamaModel
from sahyog.llm.gateway import ModelGateway, Prices, Route
from sahyog.llm.schemas import SpecialtyMatch
from sahyog.llm.types import (
    BoundaryViolation,
    ModelRefused,
    ModelRequest,
    ModelTimeout,
    ModelUnavailable,
    SchemaRejected,
)
from sahyog.safety.deid import KnownIdentity

OK = '{"specialty_id": "SP12", "alternative": null, "confidence": 0.8}'
PRICES = Prices(Path("config/prices.yaml"))


def gateway(primary, fallback=None, **kw):
    adapters = {"primary": primary} | ({"fallback": fallback} if fallback else {})
    routes = {
        "small": Route("primary", "claude-haiku-5-5"),
        "in_region": Route("primary", "llama3.1:8b"),
    }
    fallbacks = {"small": Route("fallback", "llama3.1:8b")} if fallback else {}
    return ModelGateway(adapters, routes, fallbacks, PRICES, **kw)


def call(gw, task="small", prompt="knee pain", **kw):
    return gw.complete(
        task, system="sys", prompt=prompt, schema=SpecialtyMatch, trace_id="trace-1", **kw
    )


def test_timeout_is_retried_once_then_the_fallback_answers_with_the_same_trace():
    primary = FakeModel(Sequence(ModelTimeout("slow")))
    fallback = FakeModel(OK, name="fallback", in_boundary=True)
    result = call(gateway(primary, fallback))
    assert result.output.specialty_id == "SP12"
    assert [a.outcome for a in result.record.attempts] == ["timeout", "timeout", "ok"]
    assert result.record.provider == "fallback"
    assert {r.trace_id for r in primary.received + fallback.received} == {"trace-1"}


def test_refusal_skips_the_retry():
    primary = FakeModel(Sequence(ModelRefused("no")))
    result = call(gateway(primary, FakeModel(OK, name="fallback", in_boundary=True)))
    assert [a.outcome for a in result.record.attempts] == ["refused", "ok"]


def test_all_providers_down_raises_the_last_error():
    with pytest.raises(ModelUnavailable):
        call(gateway(FakeModel(Sequence(ModelUnavailable("down")))))


def test_malformed_reply_is_rejected_not_retried_and_not_repaired():
    primary = FakeModel('Sure! {"specialty_id": "SP12", "confidence": 0.8}')
    fallback = FakeModel(OK, name="fallback", in_boundary=True)
    with pytest.raises(SchemaRejected) as e:
        call(gateway(primary, fallback))
    assert e.value.raw.startswith("Sure!")
    assert len(primary.received) == 1 and not fallback.received


def test_identifiers_are_scrubbed_before_leaving_and_restored_after():
    patient = KnownIdentity("Urvashi Kulkarni", "+91 5522579937")
    primary = FakeModel(lambda req: json.dumps({"received": "<PERSON_1>" in req.prompt}))
    gw = ModelGateway({"p": primary}, {"small": Route("p", "fake-small")}, {}, PRICES)
    from sahyog.llm.schemas import Ack

    result = gw.complete(
        "small",
        system="s",
        prompt="Urvashi Kulkarni, 5522579937",
        schema=Ack,
        trace_id="t",
        patient=patient,
    )
    assert result.output.received
    assert primary.received[0].prompt == "<PERSON_1>, <PHONE_1>"
    assert result.record.scrubbed == {"PERSON": 1, "PHONE": 1}


def test_in_region_calls_are_not_scrubbed_and_never_leave_the_boundary():
    inside = FakeModel(OK, in_boundary=True)
    call(gateway(inside), task="in_region", prompt="Urvashi Kulkarni")
    assert inside.received[0].prompt == "Urvashi Kulkarni"
    with pytest.raises(BoundaryViolation):
        call(gateway(FakeModel(OK)), task="in_region")


def test_cost_comes_from_the_price_file():
    result = call(gateway(FakeModel(OK)))
    r = result.record
    assert r.cost_usd == pytest.approx((r.input_tokens * 0.10 + r.output_tokens * 0.50) / 1e6)
    assert PRICES.as_of == "2026-10-06"


def test_no_vendor_sdk_outside_the_adapters():
    offenders = []
    for path in Path("sahyog").rglob("*.py"):
        if "llm/adapters" in path.as_posix():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [
                f"{path}: {n}"
                for n in names
                if n.split(".")[0] in ("anthropic", "openai", "google", "ollama")
            ]
    assert offenders == []


# ---- adapters against stubbed HTTP -------------------------------------------------------

REQUEST = ModelRequest(
    model="claude-sonnet-5-5",
    system="sys",
    prompt="hi",
    json_schema={"type": "object"},
    timeout_s=5,
    trace_id="t",
)


def anthropic_with(handler):
    from anthropic import DefaultHttpxClient

    client = DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    return AnthropicModel("test-key-not-real", http_client=client)


def message(stop_reason="end_turn", text=OK):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 7},
    }


def test_anthropic_request_shape():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        return httpx2.Response(200, json=message())

    reply = anthropic_with(handler).generate(REQUEST)
    body = seen["body"]
    assert reply.text == OK and (reply.input_tokens, reply.output_tokens) == (12, 7)
    assert body["output_config"]["format"] == {"type": "json_schema", "schema": {"type": "object"}}
    assert not {"temperature", "top_p", "top_k"} & body.keys()
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen["headers"]["anthropic-beta"]


def test_anthropic_haiku_has_no_server_fallback():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=message())

    haiku = ModelRequest(**{**REQUEST.__dict__, "model": "claude-haiku-5-5"})
    anthropic_with(handler).generate(haiku)
    assert "fallbacks" not in seen["body"]


def test_anthropic_errors_map_to_gateway_errors():
    with pytest.raises(ModelRefused):
        anthropic_with(lambda r: httpx2.Response(200, json=message("refusal"))).generate(REQUEST)
    overloaded = {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
    with pytest.raises(ModelUnavailable):
        anthropic_with(lambda r: httpx2.Response(529, json=overloaded)).generate(REQUEST)


def test_ollama_adapter():
    def handler(request):
        body = json.loads(request.content)
        assert body["format"] == {"type": "object"} and body["stream"] is False
        return httpx.Response(
            200,
            json={
                "model": "llama3.1:8b",
                "message": {"content": OK},
                "prompt_eval_count": 20,
                "eval_count": 9,
            },
        )

    model = OllamaModel("http://ollama", transport=httpx.MockTransport(handler))
    reply = model.generate(REQUEST)
    assert reply.text == OK and reply.output_tokens == 9
    down = OllamaModel(
        "http://ollama", transport=httpx.MockTransport(lambda r: httpx.Response(503))
    )
    with pytest.raises(ModelUnavailable):
        down.generate(REQUEST)
