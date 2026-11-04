from datetime import date

import pytest

from sahyog.safety.deid import KnownIdentity, Scrubber, age_band

TODAY = date(2026, 10, 30)
PATIENT = KnownIdentity("Bakhshi Date", "+91 5557790557", "22-5799-3712-3456", date(1945, 6, 11))


@pytest.fixture(scope="module")
def scrubber():
    return Scrubber()


@pytest.mark.parametrize(
    "phone", ["+91 5557790557", "+915557790557", "05557790557", "55577 90557", "+91-55-5779-0557"]
)
def test_patient_phone_removed_in_any_format(scrubber, phone):
    out = scrubber.scrub(f"call me on {phone} today", patient=PATIENT, today=TODAY).text
    assert "5557790557" not in out.replace(" ", "").replace("-", "")
    assert "<PHONE_1>" in out


@pytest.mark.parametrize("abha", ["22-5799-3712-3456", "22579937123456", "22 5799 3712 3456"])
def test_abha_removed_in_any_format(scrubber, abha):
    out = scrubber.scrub(f"ABHA {abha}", patient=PATIENT, today=TODAY).text
    assert out == "ABHA <ABHA_1>"


@pytest.mark.parametrize(
    "dob",
    [
        "1945-06-11",
        "11/06/1945",
        "11 Jun 1945",
        "June 11, 1945",
        "11-Jun-1945",
        "11th June 1945",
        "11th of June 1945",
    ],
)
def test_date_of_birth_becomes_an_age_band(scrubber, dob):
    out = scrubber.scrub(f"DOB {dob}.", patient=PATIENT, today=TODAY).text
    assert out == "DOB 80–89 years."


def test_surname_that_is_a_word_keeps_the_word(scrubber):
    out = scrubber.scrub("Bakhshi Date came. Date of test 12/03/2026.", patient=PATIENT).text
    assert out == "<PERSON_1> came. Date of test 12/03/2026."


def test_pincode_becomes_district(scrubber):
    assert scrubber.scrub("pin 411038").text == "pin Pune"
    assert scrubber.scrub("pincode 999999").text == "pincode [district]"


def test_clinical_content_survives(scrubber):
    text = (
        "HbA1c 7.2% on 12/03/2026, TSH 3.1 mIU/L, Metformin 500 mg, Atorvastatin 10 mg, "
        "BP 150/95 mmHg, platelets 1,50,000 /cumm. Type 2 diabetes. Next review 05 Aug 2026."
    )
    assert scrubber.scrub(text).text == text


def test_third_party_names_without_a_name_list(scrubber):
    out = scrubber.scrub("Meera came in with Phurba Lepcha; her husband Tenzin Norbu waited.").text
    assert "Lepcha" not in out and "Tenzin" not in out


def test_hinglish_is_not_mistaken_for_names(scrubber):
    out = scrubber.scrub("mera naam ravi kumar hai. Levothyroxine 50 mcg le raha hoon.").text
    assert out == "mera naam <PERSON_1> hai. Levothyroxine 50 mcg le raha hoon."


def test_same_value_gets_the_same_placeholder_and_reidentifies(scrubber):
    r = scrubber.scrub("Bakhshi Date said bakhshi date is fine", patient=PATIENT)
    assert r.text == "<PERSON_1> said <PERSON_1> is fine"
    assert r.reidentify("Hello <PERSON_1>") == "Hello Bakhshi Date"


def test_age_bands():
    assert age_band(date(2026, 1, 1), TODAY) == "under 1 year"
    assert age_band(date(1990, 10, 31), TODAY) == "30–39 years"
    assert age_band(date(1990, 10, 30), TODAY) == "30–39 years"


def test_known_name_in_devanagari_is_scrubbed(scrubber):
    """S1's known limitation, closed in S2: the patient's Devanagari name is stored and removed."""
    ravi = KnownIdentity("Ravi Kulkarni", "+91 5511223344", name_local="रवि कुलकर्णी")
    out = scrubber.scrub("रवि कुलकर्णी को सीने में दर्द है", patient=ravi, today=TODAY).text
    assert "रवि" not in out and "कुलकर्णी" not in out
    assert "सीने में दर्द" in out


@pytest.mark.parametrize(
    ("name_local", "sentence", "kept"),
    [
        ("बल रंगन", "बलगम में खून आ रहा है", "बलगम"),
        ("राम कुमार", "आराम नहीं मिल रहा", "आराम नहीं"),
        ("सुनील काम", "काम करते समय सीने में दर्द", "काम करते"),
    ],
)
def test_devanagari_name_parts_never_cut_into_other_words(scrubber, name_local, sentence, kept):
    """From the S2 review: name parts were removed as substrings, damaging symptom words."""
    p = KnownIdentity("Test Patient", "+91 5500000000", name_local=name_local)
    assert kept in scrubber.scrub(sentence, patient=p, today=TODAY).text


@pytest.mark.parametrize(
    ("name_local", "sentence", "name_part"),
    [
        ("रवि कुलकर्णी", "रवि को सीने में दर्द है", "रवि"),
        ("अमित सेन", "सेन को बुखार है", "सेन"),
        ("रवि कुलकर्णी", "मरीज़ का नाम रवि।", "रवि"),
    ],
)
def test_a_short_devanagari_name_on_its_own_is_removed(scrubber, name_local, sentence, name_part):
    """From the S2 re-review: a length rule had let 3-letter names like रवि through."""
    p = KnownIdentity("Test Patient", "+91 5500000000", name_local=name_local)
    assert name_part not in scrubber.scrub(sentence, patient=p, today=TODAY).text


def test_every_seeded_devanagari_name_is_removed(scrubber):
    """Across the whole seed, not hand-picked names: each patient's Devanagari name, in full and
    each part on its own (except parts that are everyday words), never leaves."""
    from sqlalchemy import select

    from sahyog.db import get_sessionmaker
    from sahyog.models import Patient
    from sahyog.safety.deid import DEVANAGARI_WORD_NAMES

    with get_sessionmaker()() as session:
        patients = session.scalars(select(Patient)).all()
    assert patients
    for patient in patients:
        known = KnownIdentity.from_patient(patient)
        parts = [w for w in patient.name_local.split() if w not in DEVANAGARI_WORD_NAMES]
        for form in [patient.name_local, *parts]:
            out = scrubber.scrub(f"{form} को बुखार है।", patient=known, today=TODAY).text
            assert form not in out and "बुखार" in out, (patient.patient_id, form, out)
