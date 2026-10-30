"""Transcript grounding, in code: the model structures what the doctor said and never prescribes.

Every A and P line must quote the doctor. A medicine needs a span in the doctor's words. A class
with no molecule, or a molecule with no dose, stays a gap for the doctor to fill. A known drug name
or a number in the plan that was never said is replaced by a gap.
"""

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

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
    q = normalise(quote).strip(" .,")
    return bool(q) and fuzz.partial_ratio(q, normalise(source)) >= threshold


@dataclass
class GroundedMeds:
    medicines: list[dict] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


def ground_medicines(raw: list[dict], doctor: str) -> GroundedMeds:
    out = GroundedMeds()
    seen = set()
    for m in raw:
        name, span = m["name"].strip(), m["span"].strip()
        key = normalise(name)
        if key in seen:
            continue
        seen.add(key)
        if not quoted(span, doctor, SPAN_MATCH) or not quoted(name, doctor, SPAN_MATCH):
            out.dropped.append(name)
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
        dose = m.get("dose") or ""
        said = bool(dose) and any(n in normalise(doctor) for n in DOSE.findall(dose.lower()))
        if dose and not said:
            dose = ""
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
    words = name.split()
    return any(c in (name, *words) or name.endswith(f" {c}") for c in DRUG_CLASSES)


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
