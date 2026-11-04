"""De-identification and egress scrubber: nothing that identifies a patient leaves the boundary.

Order, each pass adding spans that are resolved together (longest wins on overlap):

1. Known identifiers: the patient's own name, phone, ABHA and date of birth, in every format.
2. Indian patterns: ABHA, Aadhaar-like numbers, phones, emails, pincodes, labelled dates of birth.
3. Names: Presidio with spaCy, a gazetteer of Indian names (which spaCy's small model misses), and
   two structural rules that need no name list: capitalised words after a relationship or
   introduction cue ("her husband", "I am", "Mrs"), and capitalised word pairs mid-sentence.

Direct identifiers become placeholders (<PERSON_1>). Quasi-identifiers are generalised as the spec
says: date of birth to an age band, pincode to a district. The placeholder map lives only in the
returned ScrubResult, for re-identifying a reply; it is never stored or sent anywhere.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cache
from typing import Literal

from sahyog.safety.language import HINGLISH
from sahyog.seed.catalogue import MEDICINES

Kind = Literal["PERSON", "PHONE", "ABHA", "AADHAAR", "EMAIL", "PINCODE", "DOB"]

# Words that are also Indian names: matched as a name only next to another name or an honorific
AMBIGUOUS_NAMES = frozenset(
    """
    agate amble bail bal bath ben chad char dar dash date de deep din doctor forum gala harsh jack
    kale kar lad loyal lucky mall mann mason master merchant more oak om pal pant ray sandal sane
    tailor tank victor warrior
    """.split()
)
HONORIFICS = frozenset("mr mrs ms miss dr shri smt sri kumari master".split())
# Words after which the next capitalised words are a person's name
NAME_CUES = HONORIFICS | frozenset(
    """
    husband wife son daughter mother father brother sister friend neighbour neighbor uncle aunt
    grandfather grandmother caregiver attendant patient am naam called named beta beti bhai behen
    """.split()
)
# Capitalised words that are not names: places, calendar, the network's own name
NOT_NAMES = frozenset(
    """
    sahyog pune mumbai thane nagpur nashik india maharashtra kothrud hadapsar aundh andheri dadar
    january february march april may june july august september october november december
    jan feb mar apr jun jul aug sep sept oct nov dec monday tuesday wednesday thursday friday
    saturday sunday i the a an my her his their our your this that patient consultation note
    question reports report plan contact email phone seen dob born next review vitamin type
    """.split()
)

# Words on reports that the capitalised-pair rule and NER take for names ("Total Cholesterol")
REPORT_WORDS = frozenset(
    """
    test tests result results unit units reference range value normal laboratory lab summary
    discharge hospital course investigation investigations biochemistry haematology hematology
    pathology radiology microbiology serology diagnosis history medicine medicines medication
    prescription advice treatment findings impression sample specimen collected received reported
    date page name age sex gender male female consultant referred referrer ward bed admission
    admitted blood sugar fasting post prandial random glucose total cholesterol triglycerides
    haemoglobin hemoglobin platelet platelets count serum creatinine urea uric acid calcium sodium
    potassium chloride bilirubin albumin protein globulin liver kidney renal function thyroid lipid
    profile complete neutrophils lymphocytes monocytes eosinophils basophils hematocrit iron
    ferritin urine stool culture sensitivity ultrasound scan chest abdomen pelvis diagnostics
    notes continued synthetic department follow up chief complaint complaints past medical on
    """.split()
)
# A table row: a value then a unit. Its words are a test's name, not a person's
LAB_ROW = re.compile(
    r"\d[\d.,]*\s*(?:%|(?:mg|g|ng|pg|mcg|ug|µg|iu|miu|u|mmol|meq|lakh|thou|cells|fl|mm|sec|ml)\b)",
    re.IGNORECASE,
)

# Clinical vocabulary that must survive (NER sometimes tags drug names as people)
CLINICAL_ALLOW = frozenset(
    {m[1].split()[0] for m in MEDICINES}
    | {"HbA1c", "TSH", "LDL", "HDL", "ECG", "MRI", "CT", "BP", "CBC", "ESR", "CRP", "SGPT", "SGOT"}
    | {"ABHA", "Aadhaar", "OPD", "IPD", "Plan", "Rx"}
)
CLINICAL_ALLOW_LOWER = frozenset(w.lower() for w in CLINICAL_ALLOW) | REPORT_WORDS
# Never part of a name: dose units and frequencies (NER on "50 mcg le" tags "mcg le")
UNITS = frozenset("mg mcg ml g dl iu mmol mmhg kg cm tab tablet tabs cap od bd tds daily".split())

# Pincode prefix → district for the seeded cities; anything else is removed, not generalised
PIN_DISTRICTS = {
    "411": "Pune",
    "412": "Pune",
    "400": "Mumbai",
    "401": "Thane",
    "421": "Thane",
    "440": "Nagpur",
    "441": "Nagpur",
    "422": "Nashik",
}

ABHA = re.compile(r"(?<!\d)\d{2}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}(?!\d)")
AADHAAR = re.compile(r"(?<!\d)[2-9]\d{3}[-\s]?\d{4}[-\s]?\d{4}(?!\d)")
# 10 digits starting 5-9, optional +91/91/0 prefix, any spacing or hyphens
PHONE = re.compile(r"(?<![\d+])(?:\+?91[-\s]?|0)?[5-9](?:[-\s]?\d){9}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PINCODE = re.compile(
    r"(?:\b(?:pin\s?code|pincode|pin|postal code)\b\s*[:\-]?\s*|"
    r"\b(?:pune|mumbai|thane|nagpur|nashik)\b[\s,\-]+)([1-9]\d{2}\s?\d{3})(?!\d)",
    re.IGNORECASE,
)
DATE = (
    r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}"
)
LABELLED_DOB = re.compile(
    rf"\b(?:dob|d\.o\.b\.?|date of birth|born on|born|janm tithi)\b\s*[:\-]?\s*({DATE})",
    re.IGNORECASE,
)
WORD = re.compile(r"[A-Za-z][A-Za-z0-9'.-]*")  # digits included so "HbA1c" stays one word


@dataclass(frozen=True)
class KnownIdentity:
    """Identifiers of the patient a call is about: from the database, never from the prompt."""

    name: str
    phone: str | None = None
    abha_id: str | None = None
    dob: date | None = None

    @classmethod
    def from_patient(cls, patient) -> "KnownIdentity":
        return cls(patient.name, patient.phone, patient.abha_id, patient.dob)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    kind: Kind
    replacement: str | None = None  # set for generalised values (age band, district)


@dataclass
class ScrubResult:
    text: str
    mapping: dict[str, str] = field(repr=False)  # placeholder → original; in memory only
    counts: dict[str, int]

    def reidentify(self, reply: str) -> str:
        for placeholder, original in self.mapping.items():
            reply = reply.replace(placeholder, original)
        return reply


class Scrubber:
    def __init__(self, *, use_ner: bool = True):
        self.use_ner = use_ner

    def scrub(
        self, text: str, *, patient: KnownIdentity | None = None, today: date | None = None
    ) -> ScrubResult:
        today = today or date.today()
        spans: list[Span] = []
        if patient:
            spans += _known(text, patient, today)
        spans += _patterns(text, today)
        spans += _gazetteer(text)
        spans += _structural(text)
        if self.use_ner:
            spans += _ner(text)
        return _apply(text, _resolve(spans))


# ---- passes ------------------------------------------------------------------------------


def _known(text: str, p: KnownIdentity, today: date) -> list[Span]:
    spans = []
    full = re.escape(p.name.strip())
    spans += [Span(m.start(), m.end(), "PERSON") for m in re.finditer(full, text, re.IGNORECASE)]
    for part in p.name.split():
        # Single name parts only in title case, and never a part that is also a word ("Date")
        if len(part) >= 3 and part.lower() not in AMBIGUOUS_NAMES:
            for m in re.finditer(rf"\b{re.escape(part)}\b", text):
                spans.append(Span(m.start(), m.end(), "PERSON"))
    if p.phone:
        tail = _digits(p.phone)[-10:]
        for m in re.finditer(r"[+\d][\d\s\-]{8,}\d", text):
            if _digits(m.group())[-10:] == tail:
                spans.append(Span(m.start(), m.end(), "PHONE"))
    if p.abha_id:
        target = _digits(p.abha_id)
        for m in re.finditer(r"\d[\d\s\-]{12,}\d", text):
            if _digits(m.group()) == target:
                spans.append(Span(m.start(), m.end(), "ABHA"))
    if p.dob:
        band = age_band(p.dob, today)
        for form in _date_forms(p.dob):
            for m in re.finditer(re.escape(form), text, re.IGNORECASE):
                spans.append(Span(m.start(), m.end(), "DOB", band))
    return spans


def _patterns(text: str, today: date) -> list[Span]:
    spans = [Span(m.start(), m.end(), "EMAIL") for m in EMAIL.finditer(text)]
    spans += [Span(m.start(), m.end(), "ABHA") for m in ABHA.finditer(text)]
    spans += [Span(m.start(), m.end(), "AADHAAR") for m in AADHAAR.finditer(text)]
    spans += [Span(m.start(), m.end(), "PHONE") for m in PHONE.finditer(text)]
    for m in PINCODE.finditer(text):
        pin = m.group(1).replace(" ", "")
        district = PIN_DISTRICTS.get(pin[:3], "[district]")
        spans.append(Span(m.start(1), m.end(1), "PINCODE", district))
    for m in LABELLED_DOB.finditer(text):
        born = _parse_date(m.group(1))
        band = age_band(born, today) if born else "[age]"
        spans.append(Span(m.start(1), m.end(1), "DOB", band))
    return spans


def _gazetteer(text: str) -> list[Span]:
    names = _indian_names()
    words = list(WORD.finditer(text))
    spans = []
    for i, m in enumerate(words):
        w = m.group().strip(".'-")
        key = w.lower()
        if key not in names or w in CLINICAL_ALLOW:
            continue
        prev_word = words[i - 1].group().lower().rstrip(".") if i else ""
        nxt = words[i + 1].group().strip(".'-").lower() if i + 1 < len(words) else ""
        prv = prev_word.strip("'-")
        beside_name = (nxt in names and _adjacent(text, m, words[i + 1])) or (
            prv in names and i and _adjacent(text, words[i - 1], m)
        )
        if key in AMBIGUOUS_NAMES and not (beside_name or prv in HONORIFICS):
            continue
        if not w[0].isupper() and len(w) < 4:
            continue
        spans.append(Span(m.start(), m.start() + len(m.group().rstrip(".'-")), "PERSON"))
    return spans


def _structural(text: str) -> list[Span]:
    words = list(WORD.finditer(text))
    spans = []

    def capitalised(m: re.Match) -> bool:
        w = m.group().strip(".'-")
        return len(w) >= 2 and w[0].isupper() and not w.isupper() and _is_name_word(w)

    i = 0
    while i < len(words):
        m = words[i]
        cue = m.group().strip(".'-").lower() in NAME_CUES
        if cue:
            # "my name is ravi kumar" / "mera naam ravi kumar hai": lower-case names after naam/is
            run = []
            j = i + 1
            while (
                j < len(words)
                and len(run) < 3
                and (
                    capitalised(words[j])
                    or (
                        m.group().lower() in ("naam", "named", "called")
                        and _is_name_word(words[j].group(), lower_ok=True)
                    )
                )
            ):
                run.append(words[j])
                j += 1
            if run:
                spans.append(Span(run[0].start(), _end(run[-1]), "PERSON"))
                i = j
                continue
        # Two or more capitalised words mid-sentence: "and her husband Phurba Lepcha both..."
        if (
            capitalised(m)
            and not _sentence_start(text, m.start())
            and not _on_lab_row(text, m.start())
        ):
            run = [m]
            j = i + 1
            while (
                j < len(words)
                and capitalised(words[j])
                and _adjacent(text, run[-1], words[j])
                and not run[-1].group().endswith(".")
            ):
                run.append(words[j])
                j += 1
            if len(run) >= 2:
                spans.append(Span(run[0].start(), _end(run[-1]), "PERSON"))
                i = j
                continue
        i += 1
    return spans


def _on_lab_row(text: str, pos: int) -> bool:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return bool(LAB_ROW.search(text[start : end if end != -1 else len(text)]))


def _is_name_word(w: str, *, lower_ok: bool = False) -> bool:
    key = w.strip(".'-").lower()
    if not key.isalpha() or key in NOT_NAMES or key in HINGLISH or key in UNITS:
        return False
    if key in CLINICAL_ALLOW_LOWER or key in AMBIGUOUS_NAMES:
        return False
    return lower_ok or w[0].isupper()


def _ends_sentence(prev: re.Match, cue_index: int, j: int) -> bool:
    """A name never runs past a full stop; the cue's own abbreviation dot ("Dr.") does not count."""
    return j - 1 != cue_index and prev.group().endswith(".")


def _sentence_start(text: str, pos: int) -> bool:
    before = text[:pos].rstrip()
    return not before or before[-1] in ".!?:;\n"


def _end(m: re.Match) -> int:
    return m.start() + len(m.group().rstrip(".'-"))


def _ner(text: str) -> list[Span]:
    results = _analyzer().analyze(
        text=text,
        language="en",
        entities=["PERSON", "EMAIL_ADDRESS"],
        allow_list=sorted(CLINICAL_ALLOW),
        score_threshold=0.5,
    )
    spans = []
    for r in results:
        if r.entity_type == "PERSON":
            trimmed = _trim_name(text, r.start, r.end)
            if (
                trimmed
                and _ner_name_is_plausible(text, trimmed)
                and not _on_lab_row(text, trimmed.start)
            ):
                spans.append(trimmed)
        else:
            spans.append(Span(r.start, r.end, "EMAIL"))
    return spans


def _ner_name_is_plausible(text: str, span: Span) -> bool:
    """spaCy's small English model, on patient free text, tags symptoms as people: "kerosene",
    "blurry vision", Devanagari and most Hinglish. Taking those out would blind the model to the
    complaint, so its word is taken only for capitalised Latin words, and not for a lone word
    opening a sentence ("Knee pain", "Grandpa suddenly"). Lower-case or sentence-initial names are
    left to the known-identifier pass, the name list and the cue rules."""
    words = text[span.start : span.end].split()
    if not all(re.match(r"[A-Z][a-zA-Z'’.-]*$", w) for w in words):
        return False
    if len(words) > 1:
        return True
    before = text[: span.start].rstrip()
    return bool(before) and before[-1] not in ".!?:;\n"


def _trim_name(text: str, start: int, end: int) -> Span | None:
    """Trim an NER 'person' to its name words, or drop it.

    spaCy's English model reads Hinglish as names ("mera naam", "kumar hai") and doses as names
    ("mcg le"). Hindi function words and units are cut from the edges; a span with a digit, a
    drug or lab term, or only an ambiguous word left is dropped.
    """
    words = list(re.finditer(r"\S+", text[start:end]))

    def junk(m: re.Match) -> bool:
        w = m.group().strip(".,'-:;()").lower()
        return w in HINGLISH or w in UNITS or not w

    while words and junk(words[0]):
        words.pop(0)
    while words and junk(words[-1]):
        words.pop()
    if not words:
        return None
    s, e = start + words[0].start(), start + words[-1].end()
    span = text[s:e].rstrip(".,;:")
    lowered = [w.strip(".,'-").lower() for w in span.split()]
    if any(ch.isdigit() for ch in span) or any(w in CLINICAL_ALLOW_LOWER for w in lowered):
        return None
    if len(lowered) == 1 and lowered[0] in AMBIGUOUS_NAMES:
        return None
    return Span(s, s + len(span), "PERSON")


# ---- resolution and replacement ----------------------------------------------------------


def _resolve(spans: list[Span]) -> list[Span]:
    """Keep the longest span where spans overlap; identifiers beat names on ties."""
    rank = {"ABHA": 0, "AADHAAR": 1, "PHONE": 2, "EMAIL": 3, "DOB": 4, "PINCODE": 5, "PERSON": 6}
    chosen: list[Span] = []
    for s in sorted(spans, key=lambda s: (-(s.end - s.start), rank[s.kind], s.start)):
        if all(s.end <= c.start or s.start >= c.end for c in chosen):
            chosen.append(s)
    return sorted(chosen, key=lambda s: s.start)


def _apply(text: str, spans: list[Span]) -> ScrubResult:
    mapping: dict[str, str] = {}
    by_value: dict[tuple[str, str], str] = {}
    counts: dict[str, int] = {}
    out, last = [], 0
    for s in spans:
        original = text[s.start : s.end]
        counts[s.kind] = counts.get(s.kind, 0) + 1
        if s.replacement is not None:
            replacement = s.replacement
        else:
            key = (s.kind, _canonical(s.kind, original))
            if key not in by_value:
                n = sum(1 for k in by_value if k[0] == s.kind) + 1
                by_value[key] = f"<{s.kind}_{n}>"
                mapping[by_value[key]] = original
            replacement = by_value[key]
        out += [text[last : s.start], replacement]
        last = s.end
    out.append(text[last:])
    return ScrubResult("".join(out), mapping, counts)


# ---- helpers -----------------------------------------------------------------------------


def age_band(born: date, today: date) -> str:
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if years < 1:
        return "under 1 year"
    low = years // 10 * 10
    return f"{low}–{low + 9} years"


def _date_forms(d: date) -> list[str]:
    return [
        d.isoformat(),
        f"{d.day:02d}/{d.month:02d}/{d.year}",
        f"{d.day}/{d.month}/{d.year}",
        f"{d.day:02d}-{d.month:02d}-{d.year}",
        f"{d.day:02d}.{d.month:02d}.{d.year}",
        f"{d.day} {d:%b} {d.year}",
        f"{d.day} {d:%B} {d.year}",
        f"{d:%B} {d.day}, {d.year}",
        f"{d:%b} {d.day}, {d.year}",
    ]


def _parse_date(raw: str) -> date | None:
    raw = raw.replace(",", "").strip()
    for fmt in (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d %Y",
        "%B %d %Y",
    ):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _canonical(kind: str, value: str) -> str:
    return _digits(value) if kind in ("PHONE", "ABHA", "AADHAAR") else value.lower()


def _adjacent(text: str, a: re.Match, b: re.Match) -> bool:
    return text[a.end() : b.start()].strip() == ""


@cache
def _indian_names() -> frozenset[str]:
    from faker.providers.person.en_IN import Provider

    raw = Provider.first_names_male + Provider.first_names_female + Provider.last_names
    return frozenset(n.lower() for n in raw if len(n) >= 3)


@cache
def _analyzer():
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    nlp = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
    ).create_engine()
    return AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
