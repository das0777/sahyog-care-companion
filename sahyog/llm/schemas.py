"""Output schemas for model calls. Each call has one; a reply that does not match is rejected."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SPECIALTY_ID = r"^SP\d{2}$"


class Strict(BaseModel):
    # Unknown fields are an error, not ignored: a reply with extra keys is not what we asked for
    model_config = ConfigDict(extra="forbid")


class SpecialtyMatch(Strict):
    """W1 match_specialty: one specialty, an optional alternative, a confidence."""

    specialty_id: str = Field(pattern=SPECIALTY_ID)
    alternative: str | None = Field(default=None, pattern=SPECIALTY_ID)
    confidence: float = Field(ge=0, le=1)
    wants_diagnosis_or_dose: bool = False


RedFlagCategory = Literal[
    "cardiac",
    "stroke",
    "breathing",
    "bleeding",
    "self_harm",
    "poisoning",
    "anaphylaxis",
    "seizure_or_unresponsive",
    "severe_infection",
    "head_injury",
    "pregnancy",
    "infant",
    "major_trauma_or_burn",
    "other",
]


class RedFlagSecondPass(Strict):
    """Model second pass on the red-flag gate. Adds flags only; see Decision.with_second_pass."""

    add_flags: list[RedFlagCategory] = Field(default_factory=list, max_length=5)
    reason: str = Field(max_length=300)


class ClarifyQuestion(Strict):
    """W1 clarify: one short question for the patient."""

    question: str = Field(min_length=3, max_length=200)


class ContextGrade(Strict):
    """W2 grade_context: do these excerpts hold the answer?"""

    relevant: bool


class AnswerSentence(Strict):
    text: str = Field(min_length=1, max_length=500)
    excerpts: list[int] = Field(default_factory=list, max_length=8)


class AnswerDraft(Strict):
    """W2 answer. Cites excerpt numbers, which code maps to documents, so it can't invent an id."""

    found: bool
    wants_diagnosis_or_dose: bool = False
    sentences: list[AnswerSentence] = Field(default_factory=list, max_length=12)


class JudgedClaim(Strict):
    claim: str = Field(max_length=500)
    supported: bool


class FaithfulnessJudgement(Strict):
    """Eval only: a model's judgement, uncalibrated until S7."""

    claims: list[JudgedClaim] = Field(default_factory=list, max_length=40)


class Ack(Strict):
    """Minimal reply used by the egress replay."""

    received: bool
