"""Prompt-injection scan on uploaded text. Flagged chunks are quarantined, never indexed.

A first filter only: a paraphrased instruction will get through. The real defences are S4's SQL
patient filter and citation check, which hold even if a planted instruction reaches the model.
"""

import re

from sahyog.safety.text import normalise

_PATTERNS = [
    # English
    r"\b(ignore|disregard|forget|override)\s+"
    r"((all|any|your|the|my|these|those|previous|prior|above|earlier|system|of)\s+){0,4}"
    r"(instructions?|rules?|prompts?|guidelines?)\b",
    r"\b(previous|prior|above|earlier)\s+(instructions?|rules?|prompts?)\b",
    r"\bnew\s+instructions?\b",
    r"\bsystem\s*(prompt|message)?\s*:",
    r"\byou are now\b",
    r"\b(admin|developer|debug|root)\s+mode\b",
    r"\b(reveal|show|list|send|dump|print)\b.{0,50}\b(other|every|all|another)\b.{0,30}"
    r"\b(patients?|records?|data|files?)\b",
    r"\b(data|records?)\s+of\s+(patient|p\d{3,})\b",
    r"\bp\d{4}\b",
    # Hinglish
    r"\b(instructions?|rules?|nirdesh)\b.{0,20}\b(ignore|bhool|anadekha|nazarandaz)\b",
    r"\b(doosre|dusre|sabhi|saare|sare)\b.{0,30}\b(patients?|mareez\w*|mariz\w*)\b",
    # Hindi
    r"निर्देशों?\s*को\s*(अनदेखा|नज़रअंदाज़|नजरअंदाज|भूल)",
    r"(दूसरे|सभी|अन्य)\s*(मरीज|रोगी)",
]
_INJECTION = re.compile("|".join(f"(?:{p})" for p in _PATTERNS))


def flags_injection(text: str) -> str | None:
    """The matched words, for the desk to review, or None."""
    match = _INJECTION.search(normalise(text))
    return match.group(0)[:120] if match else None
