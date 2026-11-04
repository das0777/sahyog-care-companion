"""Wrong-patient check: a report that clearly belongs to someone else is held, not indexed.

The patient filter can't catch a mix-up at upload, because the chunks would already be filed under
the wrong patient. Only a clear mismatch holds a report: one with no name is fine, and scans get
room for a misread digit or letter.
"""

import re

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from sahyog.ingest.parse import PageText
from sahyog.safety.text import normalise

ABHA = re.compile(r"(?<!\d)\d{2}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}(?!\d)")
_NAME_LINE = re.compile(
    r"(?:(?<![a-z] )\bpatient(?:'s)?\s*name|^\s*name|मरीज का नाम|^\s*नाम)"
    r"\s*[:\-]\s*(.+)",
    re.M,
)
_NAME_STOP = re.compile(r"\b(report|date|age|abha|consultant|dob|sex|gender|uhid|mobile)\b|\d|:")
NAME_SIMILARITY = 70
ABHA_OCR_DIGITS = 2


def mismatch(pages: list[PageText], *, name: str, abha_id: str) -> str | None:
    """Why this report looks like someone else's, or None."""
    own_abha = re.sub(r"\D", "", abha_id)
    for page in pages:
        room = ABHA_OCR_DIGITS if page.source == "ocr" else 0
        for found in ABHA.findall(page.text):
            digits = re.sub(r"\D", "", found)
            if Levenshtein.distance(digits, own_abha) > room:
                return "The ABHA number on this report isn't this patient's."
        for raw in _NAME_LINE.findall(normalise(page.text)):
            printed = _NAME_STOP.split(raw)[0].strip(" .,")
            if len(printed) < 3:
                continue
            if fuzz.token_set_ratio(printed, normalise(name)) < NAME_SIMILARITY:
                return "The name on this report isn't this patient's."
    return None
