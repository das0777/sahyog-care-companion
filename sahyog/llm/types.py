"""Types shared by the gateway and its adapters. Graphs see only these, never a vendor SDK."""

from dataclasses import dataclass, field
from typing import Literal, Protocol

TaskClass = Literal["small", "large", "in_region"]


@dataclass(frozen=True)
class ModelRequest:
    model: str
    system: str
    prompt: str
    json_schema: dict
    timeout_s: float
    trace_id: str
    max_tokens: int = 2048


@dataclass(frozen=True)
class ModelReply:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class Adapter(Protocol):
    name: str
    # True only for providers inside the hospital boundary (in-region, on-prem). Everything sent to
    # an adapter where this is False is scrubbed first.
    in_boundary: bool

    def generate(self, request: ModelRequest) -> ModelReply: ...


class ModelError(Exception):
    """Base for every gateway failure. Callers catch this, never a vendor exception."""


class ModelTimeout(ModelError):
    """The provider did not answer in time. Retried, then the fallback is used."""


class ModelUnavailable(ModelError):
    """Rate limit, overload, server or connection error. Retried, then the fallback is used."""


class ModelRefused(ModelError):
    """The provider declined the request. Not retried on the same provider; the fallback is used."""


class SchemaRejected(ModelError):
    """The reply did not match the output schema. Rejected, never repaired, never retried."""

    def __init__(self, message: str, raw: str):
        super().__init__(message)
        self.raw = raw


class BoundaryViolation(ModelError):
    """A call that must stay in-region had no in-boundary provider left. Fails closed."""


@dataclass
class Attempt:
    provider: str
    model: str
    outcome: Literal["ok", "timeout", "unavailable", "refused", "schema_rejected", "error"]
    latency_ms: float


@dataclass
class CallRecord:
    trace_id: str
    task: TaskClass
    provider: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    scrubbed: dict[str, int] = field(default_factory=dict)
    attempts: list[Attempt] = field(default_factory=list)
