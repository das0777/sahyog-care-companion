"""Word checks around W1. Requests for a diagnosis or dose go to a person; a model-written question
that sounds like a diagnosis or dose never reaches the patient. The full clinical-wording scan on
patient answers arrives with W2 (S4)."""

import re

from sahyog.safety.text import normalise

_ADVICE_REQUEST = [
    r"\b(what|which|how much)\b.*"
    r"\b(tablets?|medicines?|medication|dose|dosage|drugs?|antibiotics?)\b",
    r"\bprescribe\b",
    r"\bdiagnos",
    r"\bwhat (disease|illness|condition)\b",
    r"\bdo i have\b",
    r"\b(is|could) (this|it)\b.*\b(cancer|tumou?r|infection|serious|dangerous)\b",
    r"\b(kaunsi|kaun si|konsi|kitni)\b.*\b(dawa|dawai|dose|goli|tablet|medicine)\b",
    r"\b(dawa|dawai|goli)\b.*\b(batao|bataiye|leni|lun|loon)\b",
    r"\b(kaunsi|kaun si|konsi|kya) (bimari|beemari)\b",
    r"(कौन सी|कौनसी|कितनी).*(दवा|दवाई|गोली|खुराक)",
    r"(दवा|दवाई|गोली).*(बताइए|बताओ|बताएं|लेनी|लूं)",
    r"(कौन सी|कौनसी|क्या) बीमारी",
]
_CLINICAL_OUTPUT = [
    r"\bdiagnos",
    r"\b\d+\s*(mg|ml|mcg|tablets?)\b",
    r"(?<!do )\byou (may |might |could |probably )?have\b",
    r"\b(it|this) (is|may be|could be|looks like|seems like)\b",
    r"\b(take|lijiye|lena|le lo|lein)\b.*\b(tablets?|medicines?|dawa|dawai|goli|syrup)\b",
    r"\b(bimari|beemari) hai\b",
    r"बीमारी है",
    r"(दवा|दवाई|गोली) (ले|लें|लीजिए)",
]
_INTERPRETIVE_ANSWER = [
    r"\bdiagnos",
    r"\b(you|your)\b.{0,30}\b(have|has|suffer|likely|probably)\b.{0,40}"
    r"\b(disease|disorder|diabetes|anaemia|anemia|infection|failure|cancer|condition)\b",
    r"\b(this|it|these|that)\s+(indicates?|suggests?|means|shows? that|points? to)\b",
    r"\b(indicates?|suggests?|consistent with|sign of|risk of)\b",
    r"\byou\s+(should|must|need to|ought to)\b",
    r"\b(should|must)\s+(take|stop|start|increase|reduce)\b",
    r"\b(aapko|aap ko)\b.{0,30}\b(bimari|beemari|diabetes)\b",
    r"बीमारी है",
    r"(आपको|आप को).{0,30}(लेनी चाहिए|लेना चाहिए)",
]
_ADVICE = re.compile("|".join(_ADVICE_REQUEST))
_CLINICAL = re.compile("|".join(_CLINICAL_OUTPUT))
_INTERPRETIVE = re.compile("|".join(_INTERPRETIVE_ANSWER))


def asks_for_advice(text: str) -> bool:
    return bool(_ADVICE.search(normalise(text)))


_READ_BACK = re.compile(
    r"\b(did|was|were|prescribed|given|discharge|discharged|listed|report|reports|thi|the|mili)\b"
    r"|(थी|थीं|थे|रिपोर्ट|लिखी|लिखा)"
)


def asks_for_advice_on_records(text: str) -> bool:
    """W2 may read back a medicine a report lists ("which medicines was I given"), so only a
    question that isn't about what was printed goes straight to a person. The model catches the
    rest through wants_diagnosis_or_dose."""
    lowered = normalise(text)
    return bool(_ADVICE.search(lowered)) and not _READ_BACK.search(lowered)


def clinical_answer(text: str) -> bool:
    """For W2 answers, which may read back a printed dose ("Metformin 500 mg") but not interpret."""
    return bool(_INTERPRETIVE.search(normalise(text)))


def sounds_clinical(text: str) -> bool:
    return bool(_CLINICAL.search(normalise(text)))
