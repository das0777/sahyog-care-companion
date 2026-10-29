"""Output schemas for model calls. Each call has one; a reply that does not match is rejected."""

from pydantic import BaseModel, ConfigDict, Field

SPECIALTY_ID = r"^SP\d{2}$"


class Strict(BaseModel):
    # Unknown fields are an error, not ignored: a reply with extra keys is not what we asked for
    model_config = ConfigDict(extra="forbid")


class SpecialtyMatch(Strict):
    """W1 match_specialty (used from S2): one specialty, an optional alternative, a confidence."""

    specialty_id: str = Field(pattern=SPECIALTY_ID)
    alternative: str | None = Field(default=None, pattern=SPECIALTY_ID)
    confidence: float = Field(ge=0, le=1)


class RedFlagSecondPass(Strict):
    """Model second pass on the red-flag gate. Adds flags only; see Decision.with_second_pass."""

    add_flags: list[str] = Field(default_factory=list, max_length=5)
    reason: str = Field(max_length=300)


class Ack(Strict):
    """Minimal reply used by the egress replay."""

    received: bool
