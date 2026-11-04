"""Scripted W1 replies for tests, `make eval` and `make chat` without a key. Keyword rules, not a
model: these replies prove the graph's paths, and say nothing about real accuracy."""

import json
import re

from sahyog.llm.types import ModelRequest

_SPECIALTY_WORDS = {
    "SP12": ("knee", "ghutne", "back pain", "peeth"),
    "SP11": ("rash", "skin", "itchy", "khujli"),
    "SP04": ("acidity", "stomach", "pet mein", "heartburn"),
    "SP30": ("tooth", "daant"),
    "SP13": ("ear", "kaan", "throat", "gale"),
    "SP14": ("eye", "aankh", "vision"),
    "SP05": ("cough", "khansi"),
    "SP09": ("sugar", "diabetes"),
    "SP19": ("urine", "peshab"),
    "SP38": ("fake-emergency-medicine",),
}
_SECOND_PASS_WORDS = ("fake-model-flag",)


def _has(words: tuple[str, ...], text: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def triage_script(request: ModelRequest) -> str:
    # Only the patient's words: "ear" must not match the "years" in the age band
    text = request.prompt.lower().partition("<patient_message>")[2]
    if request.system.startswith("W1 second pass"):
        flags = ["other"] if _has(_SECOND_PASS_WORDS, text) else []
        return json.dumps({"add_flags": flags, "reason": "scripted reply"})
    if request.system.startswith("W1 clarify"):
        return json.dumps({"question": "Where is the problem, and how long has it lasted?"})
    if request.system.startswith("W1 specialty match"):
        for sid, words in _SPECIALTY_WORDS.items():
            if _has(words, text):
                return json.dumps(
                    {
                        "specialty_id": sid,
                        "alternative": None,
                        "confidence": 0.9,
                        "wants_diagnosis_or_dose": False,
                    }
                )
        return json.dumps(
            {
                "specialty_id": "SP01",
                "alternative": None,
                "confidence": 0.3,
                "wants_diagnosis_or_dose": False,
            }
        )
    if request.system.startswith("W3 draft"):
        return _w3_draft(request.prompt)
    if request.system.startswith("W3 medicines"):
        return _w3_meds(request.prompt)
    if request.system.startswith("W2 grade"):
        return json.dumps({"relevant": True})
    if request.system.startswith("W2 answer"):
        return _w2_answer(request.prompt)
    return "{}"


def _transcript(prompt: str) -> str:
    return prompt.partition("<transcript>")[2].partition("</transcript>")[0].strip()


def _w3_draft(prompt: str) -> str:
    """Every sentence goes in the plan, quoted exactly. Enough to prove the graph's paths."""
    sentences = [s.strip() for s in re.split(r"(?<=[.?!])\s+", _transcript(prompt)) if s.strip()]
    lines = [{"text": s, "quote": s} for s in sentences]
    return json.dumps({"subjective": [], "objective": [], "assessment": [], "plan": lines})


def _w3_meds(prompt: str) -> str:
    meds = []
    for name, dose in re.findall(
        r"\b(metformin|atorvastatin|paracetamol|amlodipine)\s*(\d+\s*mg)?",
        _transcript(prompt),
        re.I,
    ):
        meds.append({"name": name, "dose": dose, "span": f"{name} {dose}".strip()})
    for name in ("statin",):
        if re.search(rf"\blow dose {name}\b", _transcript(prompt), re.I):
            meds.append({"name": name, "dose": "", "span": f"low dose {name}"})
    return json.dumps({"medicines": meds})


def _w2_answer(prompt: str) -> str:
    """Reads back the first excerpt line that shares a word with the question."""
    excerpts, _, question = prompt.partition("</excerpts>")
    words = set(re.findall(r"[a-z0-9]{3,}", question.lower())) - {"what", "was", "the", "question"}
    for number, body in re.findall(r"\[(\d+)\][^\n]*\n(.*?)(?=\n\n\[|\Z)", excerpts, re.S):
        for line in body.splitlines():
            if words & set(re.findall(r"[a-z0-9]{3,}", line.lower())):
                sentence = {"text": line.strip(), "excerpts": [int(number)]}
                return json.dumps(
                    {"found": True, "wants_diagnosis_or_dose": False, "sentences": [sentence]}
                )
    return json.dumps({"found": False, "wants_diagnosis_or_dose": False, "sentences": []})
