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
    r"(?:(?<![a-z] )\bpatient(?:'s)?\s*name|\bname\s+of\s+(?:the\s+)?patient|\bpt\.?\s*name"
    r"|^\s*patient|^\s*name|मरीज का नाम|^\s*नाम)"
    r"\s*[:\-]\s*(.*)(?:\n\s*(.+))?",
    re.M,
)
_NAME_STOP = re.compile(r"\b(report|date|age|abha|consultant|dob|sex|gender|uhid|mobile)\b|\d|:")
WORD_SIMILARITY = 85  # each printed word against the patient's name words; scans get a little less
OCR_WORD_SIMILARITY = 75
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
        for same_line, next_line in _NAME_LINE.findall(normalise(page.text)):
            # The name may follow the label on the same line, or sit on the line below it
            raw = same_line if same_line.strip() else next_line
            # The patient's full name first, before cutting at words like "date": a surname can
            # be one of those words ("Bakhshi Date")
            own = normalise(name)
            least = OCR_WORD_SIMILARITY if page.source == "ocr" else WORD_SIMILARITY
            if fuzz.ratio(raw.strip()[: len(own)], own) >= least:
                continue
            printed = _NAME_STOP.split(raw)[0].strip(" .,")
            if len(printed) < 3:
                continue
            if not _same_person(printed, normalise(name), page.source == "ocr"):
                return "The name on this report isn't this patient's."
    return None


def _same_person(printed: str, name: str, ocr: bool) -> bool:
    """Every printed word must be one of the patient's name words (an initial may stand for one).
    A shared surname isn't enough: "Rahul Sharma" on Priya Sharma's upload is someone else's
    report, and a surname alone ("Sharma") can't confirm whose it is."""
    words = [w for w in re.split(r"[\s.]+", printed) if w]
    own = name.split()
    if len(words) < 2 and len(own) >= 2:
        return False
    least = OCR_WORD_SIMILARITY if ocr else WORD_SIMILARITY
    for w in words:
        if len(w) == 1:
            if not any(o.startswith(w) for o in own):
                return False
        elif max(fuzz.ratio(w, o) for o in own) < least:
            return False
    return True
