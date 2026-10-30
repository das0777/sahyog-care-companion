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
_ADVICE = re.compile("|".join(_ADVICE_REQUEST))
_CLINICAL = re.compile("|".join(_CLINICAL_OUTPUT))


def asks_for_advice(text: str) -> bool:
    return bool(_ADVICE.search(normalise(text)))


def sounds_clinical(text: str) -> bool:
    return bool(_CLINICAL.search(normalise(text)))
