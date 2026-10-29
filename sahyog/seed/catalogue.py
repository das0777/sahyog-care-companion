"""Reference catalogue for the synthetic seed.

Red-flag rules (red_flags.yaml) are a starter list for the S1 rule engine, not clinical guidance:
reviewed_by stays null until a clinician signs them off (the spec's crosswalk reviewer mark).
"""

from functools import cache
from pathlib import Path

import yaml

RED_FLAGS_FILE = Path(__file__).with_name("red_flags.yaml")


@cache
def _red_flags() -> dict:
    return yaml.safe_load(RED_FLAGS_FILE.read_text(encoding="utf-8"))


def red_flag_rules_for(specialty_id: str) -> dict:
    """The JSON stored in Specialty.red_flag_rules: global rules plus the specialty's own."""
    rules = _red_flags()
    return {
        "version": str(rules["version"]),
        "reviewed_by": rules["reviewed_by"],
        "global": rules["global"],
        "specific": rules["specific"].get(specialty_id, []),
    }


# (specialty_id, name, weight for doctor distribution); red flags live in red_flags.yaml
SPECIALTIES: list[tuple[str, str, int]] = [
    ("SP01", "General Medicine", 40),
    ("SP02", "Family Medicine", 25),
    ("SP03", "Cardiology", 20),
    ("SP04", "Gastroenterology", 14),
    ("SP05", "Pulmonology", 12),
    ("SP06", "Neurology", 12),
    ("SP07", "Nephrology", 8),
    ("SP08", "Endocrinology", 8),
    ("SP09", "Diabetology", 14),
    ("SP10", "Rheumatology", 6),
    ("SP11", "Dermatology", 16),
    ("SP12", "Orthopaedics", 20),
    ("SP13", "ENT", 14),
    ("SP14", "Ophthalmology", 14),
    ("SP15", "Obstetrics and Gynaecology", 22),
    ("SP16", "Paediatrics", 22),
    ("SP17", "Neonatology", 4),
    ("SP18", "Psychiatry", 10),
    ("SP19", "Urology", 8),
    ("SP20", "Oncology", 8),
    ("SP21", "Haematology", 4),
    ("SP22", "Infectious Diseases", 6),
    ("SP23", "Hepatology", 4),
    ("SP24", "General Surgery", 16),
    ("SP25", "Neurosurgery", 4),
    ("SP26", "Cardiothoracic Surgery", 3),
    ("SP27", "Vascular Surgery", 3),
    ("SP28", "Plastic Surgery", 3),
    ("SP29", "Paediatric Surgery", 3),
    ("SP30", "Dentistry", 14),
    ("SP31", "Physiotherapy", 10),
    ("SP32", "Geriatrics", 6),
    ("SP33", "Allergy and Immunology", 4),
    ("SP34", "Sports Medicine", 3),
    ("SP35", "Pain Management", 3),
    ("SP36", "Nutrition and Dietetics", 4),
    ("SP37", "Sleep Medicine", 2),
    ("SP38", "Emergency Medicine", 6),
]

# (clinic_id, name, city)
CLINICS: list[tuple[str, str, str]] = [
    ("C01", "Sahyog Kothrud", "Pune"),
    ("C02", "Sahyog Hadapsar", "Pune"),
    ("C03", "Sahyog Aundh", "Pune"),
    ("C04", "Sahyog Andheri", "Mumbai"),
    ("C05", "Sahyog Dadar", "Mumbai"),
    ("C06", "Sahyog Thane", "Mumbai"),
    ("C07", "Sahyog Sitabuldi", "Nagpur"),
    ("C08", "Sahyog Dharampeth", "Nagpur"),
    ("C09", "Sahyog Wardha Road", "Nagpur"),
    ("C10", "Sahyog College Road", "Nashik"),
    ("C11", "Sahyog Panchavati", "Nashik"),
    ("C12", "Sahyog Cidco", "Nashik"),
]

# Block start hours (IST): mornings and afternoons inside 09:00-17:00 clinic hours
BLOCK_HOURS = [9, 10, 11, 14, 15, 16]

# (medicine_id, name, composition, price in INR)
MEDICINES: list[tuple[str, str, str, str]] = [
    ("M001", "Paracetamol 500", "Paracetamol 500 mg", "18.50"),
    ("M002", "Paracetamol 650", "Paracetamol 650 mg", "30.00"),
    ("M003", "Ibuprofen 400", "Ibuprofen 400 mg", "22.00"),
    ("M004", "Amoxicillin 500", "Amoxicillin 500 mg", "95.00"),
    ("M005", "Azithromycin 500", "Azithromycin 500 mg", "120.00"),
    ("M006", "Cetirizine 10", "Cetirizine 10 mg", "20.00"),
    ("M007", "Pantoprazole 40", "Pantoprazole 40 mg", "110.00"),
    ("M008", "Omeprazole 20", "Omeprazole 20 mg", "65.00"),
    ("M009", "Metformin 500", "Metformin 500 mg", "35.00"),
    ("M010", "Metformin 1000", "Metformin 1000 mg", "60.00"),
    ("M011", "Glimepiride 1", "Glimepiride 1 mg", "55.00"),
    ("M012", "Amlodipine 5", "Amlodipine 5 mg", "40.00"),
    ("M013", "Telmisartan 40", "Telmisartan 40 mg", "85.00"),
    ("M014", "Atorvastatin 10", "Atorvastatin 10 mg", "90.00"),
    ("M015", "Aspirin 75", "Aspirin 75 mg", "12.00"),
    ("M016", "Clopidogrel 75", "Clopidogrel 75 mg", "95.00"),
    ("M017", "Levothyroxine 50", "Levothyroxine 50 mcg", "130.00"),
    ("M018", "Salbutamol inhaler", "Salbutamol 100 mcg/dose", "160.00"),
    ("M019", "Montelukast 10", "Montelukast 10 mg", "140.00"),
    ("M020", "ORS sachet", "Oral rehydration salts", "21.00"),
    ("M021", "Ondansetron 4", "Ondansetron 4 mg", "45.00"),
    ("M022", "Domperidone 10", "Domperidone 10 mg", "30.00"),
    ("M023", "Ciprofloxacin 500", "Ciprofloxacin 500 mg", "70.00"),
    ("M024", "Doxycycline 100", "Doxycycline 100 mg", "80.00"),
    ("M025", "Iron folic acid", "Ferrous sulphate + folic acid", "25.00"),
    ("M026", "Calcium + D3", "Calcium carbonate 500 mg + vitamin D3", "110.00"),
    ("M027", "Vitamin B12", "Methylcobalamin 1500 mcg", "150.00"),
    ("M028", "Diclofenac gel", "Diclofenac 1% gel", "95.00"),
    ("M029", "Insulin glargine", "Insulin glargine 100 IU/ml", "780.00"),
    ("M030", "Sertraline 50", "Sertraline 50 mg", "120.00"),
]
