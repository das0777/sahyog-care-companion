import json
from pathlib import Path

import pytest

from sahyog.db import get_sessionmaker
from sahyog.safety.language import detect
from sahyog.safety.red_flags import RedFlagEngine


def _load(name):
    return [json.loads(line) for line in Path(f"evals/w1/{name}.jsonl").read_text().splitlines()]


GOLDEN = _load("golden")
PROBES = _load("probe1") + _load("probe2")


@pytest.fixture(scope="module")
def engine():
    with get_sessionmaker()() as session:
        return RedFlagEngine.from_db(session)


def test_rules_come_from_the_database_and_match_the_catalogue(engine):
    assert engine.version == RedFlagEngine.from_catalogue().version
    assert len(engine.concepts) > 30 and engine.combos


@pytest.mark.parametrize(
    "case", [c for c in GOLDEN + PROBES if c["expect"]["red_flag"]], ids=lambda c: c["id"]
)
def test_every_golden_and_probe_red_flag_is_caught(engine, case):
    decision = engine.check(case["input"])
    assert decision.red_flag and decision.route == "emergency_desk"
    assert all(f.matched for f in decision.fired), "every rule names the words it fired on"


@pytest.mark.parametrize(
    "text",
    [
        "main ye kaam karna chahta hoon",  # one letter from "marna chahta"
        "bachcha doodh peena nahi chahta",  # one letter from "jeena nahi chahta"
        "I am fit and fine",
        "my chest x-ray report is normal",
        "bleeding gums while brushing",
        "the baby is 2 years old and has a mild cold",
        "fever since yesterday",
        "my father is 70 years old and needs a BP check",
        "neck pain from sleeping wrong",
        "I want to end the call",
        "her lips are dry",
        "my arm is sore after the vaccine",
    ],
)
def test_everyday_sentences_do_not_flag(engine, text):
    assert not engine.check(text).red_flag


def test_negation_does_not_cancel_a_flag(engine):
    # Fail safe by design (stage decision): counted as a false alarm, never a miss
    assert engine.check("no chest pain, just a cough").red_flag


def test_model_can_add_a_flag_but_never_remove_one(engine):
    flagged = engine.check("crushing chest pain")
    # The model replying "not an emergency" gives no flags to add; the rule's flag stays
    assert flagged.with_second_pass([]).red_flag
    calm = engine.check("itchy rash on my arm")
    escalated = calm.with_second_pass(["possible anaphylaxis"])
    assert escalated.red_flag and escalated.fired[-1].kind == "model"


def test_cardiac_combination_needs_a_risk_modifier(engine):
    fired = {f.rule_id for f in engine.check("ache in left arm and breathless").fired}
    assert "cardiac_pattern" not in fired
    with_age = engine.check("ache in left arm and breathless", age_years=62)
    assert "cardiac_pattern" in {f.rule_id for f in with_age.fired}


def test_typos_and_scripts(engine):
    assert engine.check("chest pian since morning").red_flag
    assert engine.check("सीने में दर्द").red_flag
    assert engine.check("saans nahi aa rahi").red_flag


def test_disabled_engine_flags_nothing(engine):
    assert not engine.check("crushing chest pain", enabled=False).red_flag


@pytest.mark.parametrize("case", GOLDEN, ids=lambda c: c["id"])
def test_language_label(case):
    assert detect(case["input"]) == case["language"]
