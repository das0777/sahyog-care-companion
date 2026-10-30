"""Speech to text, inside the boundary: audio never leaves it."""

from functools import lru_cache
from pathlib import Path

from sahyog.config import get_settings


@lru_cache
def _model():
    from faster_whisper import WhisperModel

    s = get_settings()
    return WhisperModel(
        s.whisper_model, device="cpu", compute_type="int8", download_root=s.model_cache_dir
    )


def transcribe(path: Path) -> str:
    segments, _ = _model().transcribe(str(path), vad_filter=True, beam_size=1)
    return " ".join(s.text.strip() for s in segments).strip()
