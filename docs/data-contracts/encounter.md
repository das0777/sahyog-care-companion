# encounter

| | |
|---|---|
| **Owner** | Scribe service |
| **Sensitivity** | Clinical |
| **Schema version** | 1 (migration 0001) |
| **Notes** | audio_uri expires within 24 h (E6.3). |

## Checks

- every encounter belongs to an appointment
- audio object older than 24 h does not exist

## Freshness

Live.

## Consumers, and what breaks for each

W3, doctor ownership. If the schema changes: doctor_id change lets another doctor resume a draft.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

