"""Ollama adapter: the in-region fallback, inside the hospital boundary."""

import httpx

from sahyog.llm.types import ModelError, ModelReply, ModelRequest, ModelTimeout, ModelUnavailable


class OllamaModel:
    name = "ollama"
    in_boundary = True

    def __init__(self, base_url: str, *, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(base_url=base_url, transport=transport)

    def generate(self, request: ModelRequest) -> ModelReply:
        body = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
            "format": request.json_schema,
            "stream": False,
        }
        try:
            r = self._client.post("/api/chat", json=body, timeout=request.timeout_s)
        except httpx.TimeoutException as e:
            raise ModelTimeout(str(e)) from e
        except httpx.TransportError as e:
            raise ModelUnavailable(str(e)) from e
        if r.status_code in (429, 500, 502, 503, 504):
            raise ModelUnavailable(f"ollama {r.status_code}")
        if r.status_code != 200:
            raise ModelError(f"ollama {r.status_code}: {r.text[:200]}")
        data = r.json()
        return ModelReply(
            text=data["message"]["content"],
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            model=data.get("model", request.model),
        )
