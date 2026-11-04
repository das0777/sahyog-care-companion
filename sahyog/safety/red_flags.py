"""Red-flag gate for W1: deterministic rules that run before any model sees the text.

Rules are data (Specialty.red_flag_rules, seeded from sahyog/seed/red_flags.yaml). Every decision
names the rule that fired and the words it fired on, so it can be audited. Two safety properties:

- Fail safe: negation never cancels a flag ("no chest pain" still flags; false alarms are measured).
- A model can add flags through `with_second_pass`, never remove them.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz.distance import DamerauLevenshtein
from sqlalchemy import select
from sqlalchemy.orm import Session

from sahyog.safety.language import Language, detect
from sahyog.safety.text import tokens

FUZZY_MIN_CHARS = 7  # shorter synonyms must match exactly
PHRASE_SIMILARITY = 0.88  # whole-window similarity for typo tolerance
WORD_SIMILARITY = 0.8  # per-word similarity when one inserted word is skipped

AGE_YEARS = re.compile(
    r"\bage[d]?\s*(\d{1,3})\b|\b(\d{1,3})\s*(?:years?|yrs?)\s*old\b|\b(\d{1,3})\s*(?:yo|y/o)\b"
    r"|\b(\d{1,3})\s*(?:saal|sal)\s*(?:ka|ki|ke)\b"
)
AGE_MONTHS = re.compile(r"\b(\d{1,2})\s*(?:months?|mahine)\s*(?:old|ka|ki|ke)\b")


@dataclass(frozen=True)
class Phrase:
    text: str
    words: tuple[str, ...]
    exact: bool = False

    @classmethod
    def of(cls, raw: str) -> "Phrase":
        exact = raw.startswith("=")  # see red_flags.yaml: exact match forced
        words = tuple(tokens(raw.removeprefix("=")))
        return cls(" ".join(words), words, exact)

    @property
    def fuzzy(self) -> bool:
        return not self.exact and len(self.text) >= FUZZY_MIN_CHARS


@dataclass(frozen=True)
class Concept:
    id: str
    label: str
    phrases: tuple[Phrase, ...]
    specialty_id: str | None = None


@dataclass(frozen=True)
class Combo:
    id: str
    label: str
    all_of: tuple[tuple[str, ...], ...]
    any_modifier: tuple[str, ...] = ()


@dataclass(frozen=True)
class Modifier:
    id: str
    kind: Literal["age_at_least", "age_months_below", "mention"]
    value: int | None = None
    phrases: tuple[Phrase, ...] = ()


@dataclass(frozen=True)
class Fired:
    rule_id: str
    label: str
    kind: Literal["concept", "combo", "model"]
    matched: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    red_flag: bool
    route: Literal["emergency_desk"] | None
    language: Language
    fired: tuple[Fired, ...]
    rules_version: str
    elapsed_ms: float = field(compare=False, default=0.0)

    def with_second_pass(self, model_flags: list[str]) -> "Decision":
        """Merge flags a model suggests. Union only: the model's opinion can never clear a flag."""
        extra = tuple(Fired(f"model:{f}", f, "model", ()) for f in model_flags if f)
        if not extra:
            return self
        return Decision(
            True, "emergency_desk", self.language, self.fired + extra, self.rules_version
        )


class RedFlagEngine:
    def __init__(
        self,
        concepts: list[Concept],
        signals: list[Concept],
        modifiers: list[Modifier],
        combos: list[Combo],
        version: str,
    ):
        self.concepts = concepts
        self.signals = {s.id: s for s in signals}
        self.modifiers = {m.id: m for m in modifiers}
        self.combos = combos
        self.version = version

    # ---- loading -------------------------------------------------------------------------

    @classmethod
    def from_rules(cls, rows: dict[str, dict]) -> "RedFlagEngine":
        """Build from {specialty_id: red_flag_rules}. Global rules repeat per row; dedupe by id."""
        concepts: dict[str, Concept] = {}
        signals: dict[str, Concept] = {}
        modifiers: dict[str, Modifier] = {}
        combos: dict[str, Combo] = {}
        versions = set()
        for specialty_id, rules in sorted(rows.items()):
            versions.add(rules.get("version", "unversioned"))
            g = rules.get("global", {})
            for c in g.get("concepts", []):
                concepts.setdefault(c["id"], _concept(c))
            for s in g.get("signals", []):
                signals.setdefault(s["id"], _concept(s))
            for m in g.get("modifiers", []):
                modifiers.setdefault(m["id"], _modifier(m))
            for c in g.get("combos", []):
                combos.setdefault(c["id"], _combo(c))
            for c in rules.get("specific", []):
                concepts.setdefault(c["id"], _concept(c, specialty_id))
        return cls(
            list(concepts.values()),
            list(signals.values()),
            list(modifiers.values()),
            list(combos.values()),
            ",".join(sorted(versions)),
        )

    @classmethod
    def from_db(cls, session: Session) -> "RedFlagEngine":
        from sahyog.models import Specialty

        rows = session.execute(select(Specialty.specialty_id, Specialty.red_flag_rules)).all()
        if not rows:
            raise RuntimeError("No specialties in the database: run `make seed` first")
        return cls.from_rules({sid: rules for sid, rules in rows})

    @classmethod
    def from_catalogue(cls) -> "RedFlagEngine":
        """The seed catalogue itself; used where no database is at hand."""
        from sahyog.seed.catalogue import SPECIALTIES, red_flag_rules_for

        return cls.from_rules({sid: red_flag_rules_for(sid) for sid, _, _ in SPECIALTIES})

    # ---- checking ------------------------------------------------------------------------

    def check(self, text: str, *, age_years: int | None = None, enabled: bool = True) -> Decision:
        """Decide on one intake message. `age_years` comes from the patient profile when known."""
        started = time.perf_counter()
        language = detect(text)
        words = tokens(text)
        fired: list[Fired] = []
        if enabled:
            for concept in self.concepts:
                hits = _matches(concept, words)
                if hits:
                    fired.append(Fired(concept.id, concept.label, "concept", hits))
            fired.extend(self._combos(text, words, age_years))
        return Decision(
            red_flag=bool(fired),
            route="emergency_desk" if fired else None,
            language=language,
            fired=tuple(fired),
            rules_version=self.version,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    def _combos(self, text: str, words: list[str], age_years: int | None) -> list[Fired]:
        signal_hits = {sid: _matches(s, words) for sid, s in self.signals.items()}
        signal_hits.update({c.id: _matches(c, words) for c in self.concepts})
        held = self._modifiers(text, words, age_years)
        out = []
        for combo in self.combos:
            matched: list[str] = []
            for group in combo.all_of:
                group_hits = [h for sid in group for h in signal_hits.get(sid, ())]
                if not group_hits:
                    break
                matched.extend(group_hits)
            else:
                needed = combo.any_modifier
                if needed and not any(m in held for m in needed):
                    continue
                matched.extend(held[m] for m in needed if m in held)
                out.append(Fired(combo.id, combo.label, "combo", tuple(matched)))
        return out

    def _modifiers(self, text: str, words: list[str], age_years: int | None) -> dict[str, str]:
        lowered = text.lower()
        years = _first_int(AGE_YEARS, lowered)
        if years is None:
            years = age_years
        months = _first_int(AGE_MONTHS, lowered)
        held: dict[str, str] = {}
        for m in self.modifiers.values():
            if m.kind == "age_at_least" and years is not None and years >= (m.value or 0):
                held[m.id] = f"age {years}"
            elif m.kind == "age_months_below" and months is not None and months < (m.value or 0):
                held[m.id] = f"{months} months old"
            elif m.kind == "mention":
                hits = _phrase_hits(m.phrases, words)
                if hits:
                    held[m.id] = hits[0]
        return held


# ---- matching helpers --------------------------------------------------------------------


def _matches(concept: Concept, words: list[str]) -> tuple[str, ...]:
    return tuple(_phrase_hits(concept.phrases, words))


def _phrase_hits(phrases: tuple[Phrase, ...], words: list[str]) -> list[str]:
    hits = []
    for phrase in phrases:
        hit = _find(phrase, words)
        if hit and hit not in hits:
            hits.append(hit)
    return hits


def _find(phrase: Phrase, words: list[str]) -> str | None:
    n = len(phrase.words)
    if not n or len(words) < n:
        return None
    for i in range(len(words) - n + 1):
        window = words[i : i + n]
        joined = " ".join(window)
        if joined == phrase.text:
            return joined
        if not phrase.fuzzy:
            continue
        if DamerauLevenshtein.normalized_similarity(joined, phrase.text) >= PHRASE_SIMILARITY:
            return joined
        # One inserted word inside the phrase: "pain in the chest" for "pain in chest"
        if n >= 2 and i + n < len(words):
            wider = words[i : i + n + 1]
            for skip in range(1, n):
                candidate = wider[:skip] + wider[skip + 1 :]
                if all(_word_like(a, b) for a, b in zip(candidate, phrase.words, strict=True)):
                    return " ".join(wider)
    return None


def _word_like(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) < 5:
        return False
    return DamerauLevenshtein.normalized_similarity(a, b) >= WORD_SIMILARITY


def _first_int(pattern: re.Pattern[str], text: str) -> int | None:
    m = pattern.search(text)
    if not m:
        return None
    return int(next(g for g in m.groups() if g))


def _concept(raw: dict, specialty_id: str | None = None) -> Concept:
    return Concept(
        id=raw["id"],
        label=raw.get("label", raw["id"]),
        phrases=tuple(Phrase.of(s) for s in raw["synonyms"]),
        specialty_id=specialty_id,
    )


def _modifier(raw: dict) -> Modifier:
    return Modifier(
        id=raw["id"],
        kind=raw["kind"],
        value=raw.get("value"),
        phrases=tuple(Phrase.of(s) for s in raw.get("synonyms", [])),
    )


def _combo(raw: dict) -> Combo:
    return Combo(
        id=raw["id"],
        label=raw["label"],
        all_of=tuple(tuple(g) for g in raw["all_of"]),
        any_modifier=tuple(raw.get("any_modifier", [])),
    )
