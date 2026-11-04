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
    return "{}"
