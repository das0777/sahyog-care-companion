# Data contracts

One contract per table: owner, sensitivity class, schema version and the checks that must hold. Schema version 1 is migration `0001`.

| Table | Owner | Sensitivity |
|---|---|---|
| [patient](patient.md) | Records service | Direct identifiers |
| [consent](consent.md) | Records service | Operational, tied to a patient |
| [document](document.md) | Records service | Clinical |
| [doc_chunk](doc_chunk.md) | Records service | Clinical |
| [doctor](doctor.md) | Scheduling service | Operational |
| [specialty](specialty.md) | Scheduling service | Operational |
| [clinic](clinic.md) | Scheduling service | Operational |
| [slot](slot.md) | Scheduling service | Operational |
| [appointment](appointment.md) | Scheduling service | Operational, tied to a patient |
| [encounter](encounter.md) | Scribe service | Clinical |
| [clinical_note](clinical_note.md) | Scribe service | Clinical |
| [prescription](prescription.md) | Scribe service | Clinical |
| [medicine_stock](medicine_stock.md) | Pharmacy adapter | Operational |
| [audit_event](audit_event.md) | Platform | Operational |
