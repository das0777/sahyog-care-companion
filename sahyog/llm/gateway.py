"""ModelGateway: the one way any graph calls a model.

Every call: scrub (when the provider is outside the boundary) → call → validate against the output
schema (reject, never repair) → re-identify → meter. Timeouts and outages are retried once, then the
fallback provider answers with the same trace id. A call that must stay in-region never falls back
to a provider outside the boundary.
"""

import json
import logging
import time
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from sahyog.llm.types import (
    Adapter,
    Attempt,
    BoundaryViolation,
    CallRecord,
    ModelError,
    ModelRefused,
    ModelRequest,
    ModelTimeout,
    ModelUnavailable,
    SchemaRejected,
    TaskClass,
)
from sahyog.safety.deid import KnownIdentity, Scrubber

log = logging.getLogger("sahyog.llm")


@dataclass(frozen=True)
class Route:
    provider: str
    model: str


@dataclass
class Result[T: BaseModel]:
    output: T
    record: CallRecord


class Prices:
    def __init__(self, path: Path):
        data = yaml.safe_load(path.read_text())
        self.as_of = str(data["as_of"])
        self.models: dict[str, dict] = data["models"]

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        price = self.models.get(model)
        if price is None:
            log.warning("no price for model %s in prices.yaml; cost recorded as 0", model)
            return 0.0
        return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000


class ModelGateway:
    def __init__(
        self,
        adapters: dict[str, Adapter],
        routes: dict[TaskClass, Route],
        fallbacks: dict[TaskClass, Route],
        prices: Prices,
        *,
        scrubber: Scrubber | None = None,
        timeout_s: float = 20.0,
        scrub_enabled: bool = True,
    ):
        self.adapters = adapters
        self.routes = routes
        self.fallbacks = fallbacks
        self.prices = prices
        self.scrubber = scrubber or Scrubber()
        self.timeout_s = timeout_s
        self.scrub_enabled = scrub_enabled  # off only for the GUARDRAILS=off eval run
        self.records: list[CallRecord] = []

    def complete[T: BaseModel](
        self,
        task: TaskClass,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        trace_id: str,
        patient: KnownIdentity | None = None,
        timeout_s: float | None = None,
    ) -> Result[T]:
        record = CallRecord(trace_id=trace_id, task=task)
        self.records.append(record)
        primary, fallback = self.routes[task], self.fallbacks.get(task)
        plan = [primary, primary] + ([fallback] if fallback else [])
        json_schema = _json_schema(schema)
        last_error: ModelError | None = None

        for i, route in enumerate(plan):
            if i == 1 and isinstance(last_error, ModelRefused):
                continue  # a refusal is not retried on the same provider
            adapter = self.adapters[route.provider]
            if task == "in_region" and not adapter.in_boundary:
                raise BoundaryViolation(f"in-region call would go to {route.provider}")
            sent, scrub = prompt, None
            if not adapter.in_boundary and self.scrub_enabled:
                scrub = self.scrubber.scrub(prompt, patient=patient)
                sent = scrub.text
                record.scrubbed = scrub.counts
            request = ModelRequest(
                model=route.model,
                system=system,
                prompt=sent,
                json_schema=json_schema,
                timeout_s=timeout_s or self.timeout_s,
                trace_id=trace_id,
            )
            started = time.perf_counter()
            try:
                reply = adapter.generate(request)
            except (ModelTimeout, ModelUnavailable, ModelRefused) as e:
                record.attempts.append(_attempt(route, e, started))
                last_error = e
                continue
            except ModelError as e:
                record.attempts.append(_attempt(route, e, started))
                self._log(record, "error")
                raise

            record.provider, record.model = route.provider, reply.model
            record.input_tokens += reply.input_tokens
            record.output_tokens += reply.output_tokens
            record.cost_usd += self.prices.cost(
                route.model, reply.input_tokens, reply.output_tokens
            )
            try:
                output = schema.model_validate_json(reply.text)
            except ValidationError as e:
                record.attempts.append(
                    Attempt(route.provider, route.model, "schema_rejected", _ms(started))
                )
                self._log(record, "schema_rejected")
                message = f"{schema.__name__}: {e.error_count()} validation errors"
                raise SchemaRejected(message, reply.text) from e
            record.attempts.append(Attempt(route.provider, route.model, "ok", _ms(started)))
            if scrub and scrub.mapping:
                output = schema.model_validate(_reidentify(output.model_dump(mode="json"), scrub))
            self._log(record, "ok")
            return Result(output, record)

        self._log(record, "exhausted")
        raise last_error or ModelError("no provider answered")

    def _log(self, record: CallRecord, outcome: str) -> None:
        log.info(
            json.dumps(
                {
                    "event": "model_call",
                    "outcome": outcome,
                    "trace_id": record.trace_id,
                    "task": record.task,
                    "provider": record.provider,
                    "model": record.model,
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "cost_usd": round(record.cost_usd, 6),
                    "scrubbed": record.scrubbed,
                    "attempts": [a.outcome for a in record.attempts],
                }
            )
        )


def build_gateway(settings=None) -> ModelGateway:
    """Gateway from settings. LLM_PROVIDER=fake (the S1 default) needs no key and no network."""
    from sahyog.config import get_settings

    s = settings or get_settings()
    prices = Prices(Path(s.prices_file))
    if s.llm_provider == "fake":
        from sahyog.llm.adapters.fake import FakeModel

        adapters: dict[str, Adapter] = {
            "fake": FakeModel(),
            "fake-region": FakeModel(name="fake-region", in_boundary=True),
        }
        routes: dict[TaskClass, Route] = {
            "small": Route("fake", "fake-small"),
            "large": Route("fake", "fake-large"),
            "in_region": Route("fake-region", "fake-in-region"),
        }
        fallback = Route("fake-region", "fake-in-region")
    else:
        from sahyog.llm.adapters.anthropic import AnthropicModel
        from sahyog.llm.adapters.ollama import OllamaModel

        adapters = {
            "anthropic": AnthropicModel(s.anthropic_api_key),
            "ollama": OllamaModel(s.ollama_url),
        }
        routes = {
            "small": Route("anthropic", s.llm_small_model),
            "large": Route("anthropic", s.llm_large_model),
            "in_region": Route("ollama", s.llm_in_region_model),
        }
        fallback = Route("ollama", s.llm_in_region_model)
    fallbacks: dict[TaskClass, Route] = {"small": fallback, "large": fallback}
    return ModelGateway(adapters, routes, fallbacks, prices, timeout_s=s.llm_timeout_s)


# ---- helpers -----------------------------------------------------------------------------


@cache
def _json_schema(schema: type[BaseModel]) -> dict:
    # Strict form for structured outputs; constraints the API cannot enforce move into
    # descriptions, and model_validate_json above enforces them on the reply
    from sahyog.llm.adapters.anthropic import transform_schema

    return transform_schema(schema)


def _reidentify(value, scrub):
    if isinstance(value, str):
        return scrub.reidentify(value)
    if isinstance(value, list):
        return [_reidentify(v, scrub) for v in value]
    if isinstance(value, dict):
        return {k: _reidentify(v, scrub) for k, v in value.items()}
    return value


def _attempt(route: Route, error: Exception, started: float) -> Attempt:
    outcome = {
        ModelTimeout: "timeout",
        ModelUnavailable: "unavailable",
        ModelRefused: "refused",
    }.get(type(error), "error")
    return Attempt(route.provider, route.model, outcome, _ms(started))


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
