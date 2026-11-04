"""Anthropic Messages API adapter. The only module that imports the vendor SDK.

Uses SDK 2.x (API version 2026-10-21): no sampling parameters, JSON schema via output_config.
The gateway owns retries and fallback, so the SDK's own retries are off.
"""

import anthropic
from anthropic import transform_schema  # re-exported for the gateway's schema prep

from sahyog.llm.types import (
    ModelError,
    ModelRefused,
    ModelReply,
    ModelRequest,
    ModelTimeout,
    ModelUnavailable,
)

# Models that accept the server-side refusal fallback ("default" form) on the Claude API
SERVER_FALLBACK_MODELS = frozenset({"claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"})
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"

__all__ = ["AnthropicModel", "transform_schema"]


class AnthropicModel:
    name = "anthropic"
    in_boundary = False

    def __init__(self, api_key: str, *, effort: str = "low", http_client=None):
        if not api_key:
            raise ModelError("ANTHROPIC_API_KEY is empty: add it to .env or use LLM_PROVIDER=fake")
        self.effort = effort
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=0, http_client=http_client)

    def generate(self, request: ModelRequest) -> ModelReply:
        params: dict = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.prompt}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": request.json_schema},
            },
            "metadata": {"user_id": request.trace_id},
            "timeout": request.timeout_s,
        }
        if request.model in SERVER_FALLBACK_MODELS:
            params |= {"betas": [SERVER_FALLBACK_BETA], "fallbacks": "default"}
        try:
            response = self._client.beta.messages.create(**params)
        except (anthropic.APITimeoutError, anthropic.DeadlineExceededError) as e:
            raise ModelTimeout(str(e)) from e
        except (
            anthropic.RateLimitError,
            anthropic.OverloadedError,
            anthropic.ServiceUnavailableError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
        ) as e:
            raise ModelUnavailable(str(e)) from e
        except anthropic.APIStatusError as e:
            raise ModelError(f"{e.status_code}: {e.message}") from e

        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            raise ModelRefused(f"refused ({category or 'no category'})")
        text = "".join(b.text for b in response.content if b.type == "text")
        return ModelReply(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )
