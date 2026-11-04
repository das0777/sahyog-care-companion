"""Text normalisation shared by the safety checks: English, Hinglish and Devanagari."""

import re
import unicodedata

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[a-z]")
# Devanagari vowel signs are combining marks, which \w does not cover, so name the block explicitly
TOKEN = re.compile(r"[a-z0-9ऀ-ॿ]+")


def normalise(text: str) -> str:
    """Lower-case, NFC, drop apostrophes and the nukta, unify chandrabindu with anusvara."""
    text = unicodedata.normalize("NFC", text).lower()
    text = text.replace("़", "").replace("ँ", "ं")  # तेज़ → तेज, साँस → सांस
    return re.sub(r"['’`]", "", text)


def tokens(text: str) -> list[str]:
    return TOKEN.findall(normalise(text))
