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


@pytest.mark.parametrize("dob", ["1945-06-11", "11/06/1945", "11 Jun 1945", "June 11, 1945"])
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


@pytest.mark.parametrize(
    "line",
    [
        "Fasting Blood Sugar 110 mg/dL 70-100",
        "Total Cholesterol 277 mg/dL <200",
        "Uric Acid 5.8 mg/dL 3.5-7.2",
        "Platelet Count 3.36 lakh/cumm 1.5-4.5",
        "Test Result Unit Reference",
        "Discharge Summary",
    ],
)
def test_report_wording_is_not_taken_for_a_name(scrubber, line):
    text = f"BIOCHEMISTRY\n{line}\nEnd of page"
    assert scrubber.scrub(text).text == text


def test_a_name_in_a_report_narrative_still_goes(scrubber):
    out = scrubber.scrub("Seen with her attending physician Phurba Lepcha today.").text
    assert "Lepcha" not in out
    out = scrubber.scrub("Consultant: Dr. Meera Nair\nHbA1c 7.2 %").text
    assert "Nair" not in out and "HbA1c 7.2 %" in out
