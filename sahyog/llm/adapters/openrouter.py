"""OpenRouter adapter: outside the boundary, so the gateway scrubs everything sent here.

Asks OpenRouter to use only endpoints that honour the output schema and don't collect prompts. The
gateway owns retries and fallback, so this makes one attempt.
"""

import httpx

from sahyog.llm.types import (
    ModelError,
    ModelRefused,
    ModelReply,
    ModelRequest,
    ModelTimeout,
    ModelUnavailable,
)

BASE_URL = "https://openrouter.ai/api/v1"
UNAVAILABLE = {408, 429, 500, 502, 503, 504}


class OpenRouterModel:
    name = "openrouter"
    in_boundary = False

    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {api_key}", "X-Title": "Sahyog Care Companion"},
            transport=transport,
        )

    def generate(self, request: ModelRequest) -> ModelReply:
        body = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "reply", "strict": True, "schema": request.json_schema},
            },
            "provider": {"require_parameters": True, "data_collection": "deny"},
        }
        try:
            r = self._client.post("/chat/completions", json=body, timeout=request.timeout_s)
        except httpx.TimeoutException as e:
            raise ModelTimeout(str(e)) from e
        except httpx.TransportError as e:
            raise ModelUnavailable(str(e)) from e
        _raise_for_status(r.status_code, r.text)
        data = r.json()
        # OpenRouter can report an upstream failure inside a 200
        if "error" in data:
            error = data["error"]
            _raise_for_status(int(error.get("code") or 500), str(error.get("message")))
        choice = data["choices"][0]
        message = choice["message"]
        if message.get("refusal") or choice.get("finish_reason") in ("content_filter", "refusal"):
            raise ModelRefused(f"openrouter: {choice.get('finish_reason')}")
        if choice.get("finish_reason") == "error":
            raise ModelUnavailable("openrouter: upstream error")
        usage = data.get("usage") or {}
        return ModelReply(
            text=message.get("content") or "",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", request.model),
        )


def _raise_for_status(code: int, text: str) -> None:
    if code == 200:
        return
    if code in UNAVAILABLE:
        raise ModelUnavailable(f"openrouter {code}")
    # Bad key, no credit, no endpoint: retrying can't help. The body is safe to log: it carries
    # OpenRouter's message, not our prompt
    raise ModelError(f"openrouter {code}: {text[:200]}")
