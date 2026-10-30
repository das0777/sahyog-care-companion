"""Embeddings, inside the boundary. Report text is identified, so it is never sent out for this."""

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

from sahyog.config import get_settings
from sahyog.models import EMBEDDING_DIM


class Embedder(Protocol):
    model: str

    def passages(self, texts: list[str]) -> list[list[float]]: ...

    def query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    """A multilingual model with 1,024 dimensions, via ONNX. Needs a prefix per role."""

    def __init__(self, model: str, cache_dir: str, threads: int):
        from fastembed import TextEmbedding

        self.model = model
        self._model = TextEmbedding(model, cache_dir=cache_dir, threads=threads)

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed([f"passage: {t}" for t in texts])]

    def query(self, text: str) -> list[float]:
        return next(iter(self._model.embed([f"query: {text}"]))).tolist()


class HashEmbedder:
    """For tests: fast, deterministic, no model. Says nothing about search quality."""

    model = "hash-test"

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * EMBEDDING_DIM
        for word in re.findall(r"\w+", text.lower()):
            v[int(hashlib.sha256(word.encode()).hexdigest(), 16) % EMBEDDING_DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    if s.embedder == "hash":
        return HashEmbedder()
    return LocalEmbedder(s.embedding_model, s.model_cache_dir, s.embedding_threads)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


if __name__ == "__main__":
    # The model-init service: fetch the model if it isn't there yet
    get_embedder().query("ready")
