import ast
import json
from pathlib import Path

import httpx
import httpx2
import pytest

from sahyog.llm.adapters.anthropic import AnthropicModel
from sahyog.llm.adapters.fake import FakeModel, Sequence
from sahyog.llm.adapters.ollama import OllamaModel
from sahyog.llm.adapters.openrouter import OpenRouterModel
from sahyog.llm.gateway import ModelGateway, Prices, Route
from sahyog.llm.schemas import SpecialtyMatch
from sahyog.llm.types import (
    BoundaryViolation,
    ModelError,
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


def openrouter_with(handler):
    return OpenRouterModel("test-key-not-real", transport=httpx.MockTransport(handler))


def completion(text=OK, finish_reason="stop", **message):
    return {
        "model": "anthropic/claude-sonnet-5.5",
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": text, **message},
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7},
    }


def test_openrouter_request_shape():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=completion())

    reply = openrouter_with(handler).generate(REQUEST)
    body = seen["body"]
    assert reply.text == OK and (reply.input_tokens, reply.output_tokens) == (12, 7)
    assert seen["auth"] == "Bearer test-key-not-real"
    assert body["response_format"]["json_schema"]["schema"] == {"type": "object"}
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"] == {"require_parameters": True, "data_collection": "deny"}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (429, {}, ModelUnavailable),
        (503, {}, ModelUnavailable),
        (200, {"error": {"code": 502, "message": "upstream down"}}, ModelUnavailable),
        (401, {"error": {"code": 401, "message": "bad key"}}, ModelError),
        (402, {"error": {"code": 402, "message": "no credit"}}, ModelError),
        (200, completion(finish_reason="content_filter"), ModelRefused),
        (200, completion(refusal="I can't help"), ModelRefused),
        (200, completion(finish_reason="error"), ModelUnavailable),
    ],
    ids=["429", "503", "error_in_200", "401", "402", "filtered", "refusal", "finish_error"],
)
def test_openrouter_errors_map_to_gateway_errors(status, payload, expected):
    model = openrouter_with(lambda r: httpx.Response(status, json=payload))
    with pytest.raises(expected):
        model.generate(REQUEST)


def test_openrouter_timeout_maps_to_a_gateway_timeout():
    def slow(_):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ModelTimeout):
        openrouter_with(slow).generate(REQUEST)


def test_openrouter_only_ever_receives_scrubbed_text():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion(json.dumps({"received": True})))

    from sahyog.llm.schemas import Ack

    gw = ModelGateway(
        {"openrouter": openrouter_with(handler)},
        {"small": Route("openrouter", "anthropic/claude-haiku-5.5")},
        {},
        PRICES,
    )
    result = gw.complete(
        "small",
        system="s",
        prompt="Urvashi Kulkarni, 5522579937",
        schema=Ack,
        trace_id="t",
        patient=KnownIdentity("Urvashi Kulkarni", "+91 5522579937"),
    )
    assert seen["body"]["messages"][1]["content"] == "<PERSON_1>, <PHONE_1>"
    assert result.record.cost_usd == pytest.approx((12 * 0.10 + 7 * 0.50) / 1e6)


def test_build_gateway_routes_to_openrouter_and_falls_back_inside_the_boundary():
    from sahyog.config import Settings
    from sahyog.llm.gateway import build_gateway

    gw = build_gateway(Settings(llm_provider="openrouter", openrouter_api_key="test-not-real"))
    assert gw.routes["large"] == Route("openrouter", "anthropic/claude-sonnet-5.5")
    assert gw.routes["small"] == Route("openrouter", "anthropic/claude-haiku-5.5")
    assert gw.adapters["openrouter"].in_boundary is False
    assert gw.fallbacks["large"].provider == "ollama"
    for route in gw.routes.values():
        if route.provider == "openrouter":
            assert PRICES.models[route.model]


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
