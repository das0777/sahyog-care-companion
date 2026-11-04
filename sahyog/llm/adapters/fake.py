"""Scripted, deterministic model for tests and evals. Records every request it receives."""

import json
from collections.abc import Callable

from sahyog.llm.types import ModelReply, ModelRequest

Script = Callable[[ModelRequest], str | Exception]


class FakeModel:
    def __init__(
        self,
        script: Script | str | dict | None = None,
        *,
        name: str = "fake",
        in_boundary: bool = False,
    ):
        self.name = name
        self.in_boundary = in_boundary
        self.received: list[ModelRequest] = []
        self._script = script

    def generate(self, request: ModelRequest) -> ModelReply:
        self.received.append(request)
        out = self._reply(request)
        if isinstance(out, Exception):
            raise out
        # Token counts are a stand-in: 4 characters per token, as a rough English average
        return ModelReply(
            text=out,
            input_tokens=(len(request.system) + len(request.prompt)) // 4 + 1,
            output_tokens=len(out) // 4 + 1,
            model=request.model,
        )

    def _reply(self, request: ModelRequest) -> str | Exception:
        script = self._script
        if script is None:
            return "{}"
        if isinstance(script, str):
            return script
        if isinstance(script, dict):
            return json.dumps(script)
        return script(request)


class Sequence:
    """Script that plays outcomes in order, then repeats the last one."""

    def __init__(self, *outcomes: str | Exception):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, request: ModelRequest) -> str | Exception:
        out = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        return out
