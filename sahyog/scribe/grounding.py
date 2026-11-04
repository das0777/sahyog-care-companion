"""Transcript grounding, in code: the model structures what the doctor said and never prescribes.

Every A and P line must quote the doctor. A medicine needs a span in the doctor's words. A class
with no molecule, or a molecule with no dose, stays a gap for the doctor to fill. A known drug name
or a number in the plan that was never said is replaced by a gap.
"""

import re
from dataclasses import dataclass, field

from sahyog.safety.text import normalise

QUOTE_MATCH = 90
SPAN_MATCH = 85
GAP = "[doctor to specify]"
_TURN = re.compile(r"(?:^|(?<=[.?!\s]))(Doctor|Dr|Patient|Attendant|Speaker \d)\.?\s*:", re.I)
DOSE = re.compile(r"\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|iu|units?|milligrams?|micrograms?)?\b", re.I)
DRUG_CLASSES = (
    "statin",
    "beta blocker",
    "ace inhibitor",
    "arb",
    "antibiotic",
    "antihistamine",
    "steroid",
    "diuretic",
    "painkiller",
    "analgesic",
    "antacid",
    "proton pump inhibitor",
    "ppi",
    "nsaid",
    "insulin",
    "iron",
    "vitamin",
    "antifungal",
    "antiviral",
    "anticoagulant",
    "blood thinner",
    "laxative",
    "sedative",
    "antidepressant",
    "cream",
    "ointment",
)
# Molecules the plan may name only if they were said. Not exhaustive: extract_meds' span check is
# the main defence, and this catches a plan line that names a drug the medicine list doesn't
KNOWN_MOLECULES = (
    "atorvastatin rosuvastatin simvastatin metformin glimepiride gliclazide sitagliptin insulin "
    "amlodipine telmisartan losartan ramipril enalapril metoprolol bisoprolol atenolol clopidogrel "
    "aspirin warfarin paracetamol ibuprofen diclofenac naproxen tramadol morphine pantoprazole "
    "omeprazole rabeprazole ranitidine domperidone ondansetron amoxicillin azithromycin "
    "ciprofloxacin doxycycline cefixime levothyroxine cetirizine levocetirizine montelukast "
    "salbutamol budesonide prednisolone dexamethasone hydrocortisone furosemide spironolactone"
).split()


@dataclass
class Turn:
    speaker: str
    text: str


def segment(transcript: str) -> list[Turn]:
    """Speaker labels if present. Unlabelled speech counts as the doctor's: real speaker separation
    is out of scope, and this limit is stated in the test pack."""
    parts = _TURN.split(transcript)
    if len(parts) == 1:
        return [Turn("doctor", transcript.strip())]
    turns = [Turn("doctor", parts[0].strip())] if parts[0].strip() else []
    for label, text in zip(parts[1::2], parts[2::2], strict=True):
        who = "doctor" if label.lower().startswith(("doctor", "dr")) else "patient"
        if text.strip():
            turns.append(Turn(who, text.strip()))
    return turns


def doctors_words(turns: list[Turn]) -> str:
    return " ".join(t.text for t in turns if t.speaker == "doctor")


def quoted(quote: str, source: str, threshold: int = QUOTE_MATCH) -> bool:
    """The quote must be the doctor's words exactly, after normalising case and spacing. From the
    S5 re-review: a fuzzy match let "non diabetic" stand for "known diabetic" and "stop" for
    "start". `threshold` is kept for callers and no longer loosens the match."""
    q = re.sub(r"[^\w\s]", " ", _units(normalise(quote)))
    q = " ".join(q.split())
    s = " ".join(re.sub(r"[^\w\s]", " ", _units(normalise(source))).split())
    return bool(q) and re.search(rf"(?<!\w){re.escape(q)}(?!\w)", s) is not None


@dataclass
class GroundedMeds:
    medicines: list[dict] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


# Words before a medicine that mean it isn't being prescribed ("do not give metformin")
# Any negation in a medicine's sentence: the doctor confirms, the code doesn't guess (from the S5
# re-review: phrase lists before and after the name kept missing forms like "do not take it")
# One list for both checks, with inflected forms (from the S5 re-review 3: the medicine check and
# the SOAP-line check disagreed, so "continue" could stand for "discontinue")
NEGATION_WORDS = (
    r"no|non|not|never|no longer|don't|dont|do not|deny|denies|denied|without|negative|absent"
    r"|avoid|avoids|avoided|stop|stops|stopped|stopping|discontinue|discontinues|discontinued"
    r"|discontinuing|hold|holds|held|holding|withhold|withholds|withheld|cease|ceases|ceased"
    r"|skip|skips|skipped|omit|omits|omitted|omitting|withdraw|withdraws|withdrew|withdrawn"
    r"|withdrawing|pause|pauses|paused|pausing|band|mat|nahi|nahin"
)
_NEGATION = re.compile(rf"\b(?:{NEGATION_WORDS})\b|n't\b")
# A full stop ends a sentence; the point in "2.5 mg" doesn't
_SENTENCE_END = re.compile(r"(?<!\d)\.|\.(?!\d)|[?!;\n]")
# Where what's said about one medicine ends: a new clause or the next medicine. Not a comma:
# "metformin 500 mg, twice daily" is one instruction
_CLAUSE = re.compile(r"\band\b|\bthen\b|\bplus\b|\balso\b|\bbut\b")
# Dose words that are units, not route or frequency
_UNITS = {"mg", "mcg", "g", "ml", "iu", "unit", "units", "milligram", "milligrams", "microgram"}
_UNIT_SPACE = re.compile(r"(\d)\s*(mg|mcg|g|ml|iu|units?)\b")


def _units(text: str) -> str:
    """ "5mg" and "5 mg" are the same words."""
    return _UNIT_SPACE.sub(r"\1 \2", text)


def _windows(name: str, doctor: str) -> tuple[list[str], bool]:
    """What the doctor said about this medicine, from each whole-word mention to the end of its
    clause or the next medicine; and whether any sentence mentioning it holds a negation."""
    said = _units(normalise(doctor))
    out, negated = [], False
    for m in re.finditer(rf"(?<![a-z]){re.escape(normalise(name))}(?![a-z])", said):
        start = max((x.end() for x in _SENTENCE_END.finditer(said, 0, m.start())), default=0)
        rest = said[m.end() :]
        end = _SENTENCE_END.search(rest)
        sentence = said[start : m.end() + (end.start() if end else len(rest))]
        negated = negated or bool(_NEGATION.search(sentence))
        window = rest[: end.start() if end else len(rest)]
        stops = [x.start() for x in _DRUG_SHAPE.finditer(window)]
        stops += [
            x.start() for w in KNOWN_MOLECULES for x in re.finditer(rf"(?<![a-z]){w}", window)
        ]
        stops += [x.start() for x in _CLAUSE.finditer(window)]
        # Only the first dose after the name is this medicine's: "amlodipine 5 mg, Telma 40 mg"
        numbers = list(re.finditer(r"\d+(?:\.\d+)?", window))
        stops += [numbers[1].start()] if len(numbers) > 1 else []
        # ...and a dose that sits in front of another name is that name's, even when it's the
        # only number: "Continue amlodipine, Telma 40 mg" and "Give 5 mg amlodipine, 40 mg telma"
        stops += [x.start() for x in _BRAND_BEFORE_DOSE.finditer(window)]
        stops += [
            x.start()
            for x in _DOSE_BEFORE_NAME.finditer(window)
            if x.group(1) not in _NOT_NAMES
        ]
        out.append(window[: min(stops, default=len(window))])
    return out, negated


def _dose_said(dose: str, windows: list[str]) -> bool:
    """Every number, and every route or frequency word, must sit next to this medicine."""
    d = _units(normalise(dose))
    numbers = re.findall(r"\d+(?:\.\d+)?", d)
    words = [w for w in re.findall(r"[a-z]+", d) if w not in _UNITS]
    for window in windows:
        if all(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", window) for n in numbers) and all(
            re.search(rf"\b{re.escape(w)}\b", window) for w in words
        ):
            return True
    return False


def ground_medicines(raw: list[dict], doctor: str) -> GroundedMeds:
    out = GroundedMeds()
    seen = set()
    for m in raw:
        name, span = m["name"].strip(), m["span"].strip()
        key = normalise(name)
        if key in seen:
            continue
        seen.add(key)
        if not quoted(span, doctor, SPAN_MATCH):
            out.dropped.append(name)
            continue
        # From the S5 review: the name itself must be said, as a whole word (no fuzzy match:
        # "valsartan" isn't "losartan"), and not in a negated mention ("do not give metformin")
        windows, negated = _windows(name, doctor)
        if not windows and not _is_class(key):
            out.dropped.append(name)
            continue
        if negated and not _is_class(key):
            out.gaps.append(
                {
                    "term": name,
                    "span": span,
                    "text": f"{name} [said with a negation nearby: doctor to confirm or remove]",
                }
            )
            continue
        if _is_class(key):
            out.gaps.append(
                {
                    "term": name,
                    "span": span,
                    "text": f"{name} [molecule and dose not stated: doctor to specify]",
                }
            )
            continue
        dose = (m.get("dose") or "").strip()
        if dose and not _dose_said(dose, windows):
            dose = ""  # a dose, route or frequency not said beside this medicine is a gap
        out.medicines.append(
            {
                "name": name,
                "dose": dose,
                "span": span,
                "dose_gap": not dose,
                "text": f"{name} {dose}".strip()
                if dose
                else f"{name} [dose not stated: {GAP[1:-1]}]",
            }
        )
    return out


def _is_class(name: str) -> bool:
    singular = " ".join(w.removesuffix("s") for w in name.split())
    return any(re.search(rf"\b{re.escape(c)}\b", singular) for c in DRUG_CLASSES)


_NUMBER_WORD = re.compile(
    r"\b(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:-(?:one|two|three|four|five"
    r"|six|seven|eight|nine))?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
    r"|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|hundred|thousand|half)\b"
)
_NEGATING = _NEGATION  # the same list as the medicine check
_BRAND_BEFORE_DOSE = re.compile(r"\b([a-z]{3,})\s+\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|iu|units?)?\b")
# A dose followed by a word: a name, unless the word is a route, frequency or unit (a gap, if wrong)
_DOSE_BEFORE_NAME = re.compile(r"\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|iu|units?)?\s+([a-z]{3,})\b")
_NOT_NAMES = frozenset(
    "twice thrice once daily nightly weekly hourly times time day days week weeks month months "
    "morning noon evening night bedtime at for with after before on in as and or the then oral "
    "orally tab tabs tablet tablets capsule capsules drop drops sos prn stat every needed if when "
    "until till to per of is apply inhale local topical syrup cream sachet units unit".split()
)
_DRUG_SHAPE = re.compile(
    r"\b\w+(?:pril|sartan|statin|olol|xaban|parin|dipine|prazole|mycin|cillin|floxacin|cycline"
    r"|gliptin|glitazone|formin|sprin)\b"
)


def unfaithful(text: str, quote: str, *, strict: bool) -> list[str]:
    """What a SOAP line says that its own quote doesn't: numbers (digits or words) always, and in
    the assessment and plan, drug-shaped words and capitalised names (brands) too."""
    q = normalise(quote)
    extra = [
        n
        for n in re.findall(r"\d+(?:\.\d+)?", text)
        if not re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", q)
    ]
    extra += [
        w for w in _NUMBER_WORD.findall(normalise(text)) if not re.search(rf"\b{re.escape(w)}\b", q)
    ]
    # A negation the quote doesn't hold flips the meaning ("Non diabetic" for "known diabetic")
    extra += [w for w in _NEGATING.findall(normalise(text)) if not re.search(rf"\b{w}\b", q)]
    # ...and one it drops does too ("Start metformin" for "do not start metformin")
    said_text = normalise(text)
    extra += [
        f"dropped '{w}'"
        for w in _NEGATING.findall(q)
        if not re.search(rf"\b{re.escape(w)}\b" if w[0].isalpha() else re.escape(w), said_text)
    ]
    if strict:
        # A name right before a dose ("Glycomet 500 mg", "dolo 650") must be in the quote
        extra += [w for w in _BRAND_BEFORE_DOSE.findall(normalise(text)) if w not in q]
        lowered = normalise(text)
        extra += [w for w in _DRUG_SHAPE.findall(lowered) if w not in q]
        extra += [w for w in lowered.split() if w.strip(".,") in KNOWN_MOLECULES and w not in q]
        extra += [
            w
            for w in re.findall(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{3,}\b", text)
            if w.lower() not in q
        ]
    return list(dict.fromkeys(extra))


def clean_plan_line(text: str, transcript: str) -> tuple[str, list[str]]:
    """Replace a drug or number the transcript never held. Returns the text and what was removed."""
    said = normalise(transcript)
    removed = []
    result = text
    for word in re.findall(r"[A-Za-z]+", text):
        if word.lower() in KNOWN_MOLECULES and word.lower() not in said:
            result = re.sub(rf"\b{word}\b", GAP, result)
            removed.append(word)
    for number in re.findall(r"\d+(?:\.\d+)?", result):
        if not re.search(rf"(?<![\d.]){re.escape(number)}(?![\d])", said):
            result = re.sub(rf"(?<![\d.]){re.escape(number)}(?![\d])", GAP, result)
            removed.append(number)
    return result, removed
