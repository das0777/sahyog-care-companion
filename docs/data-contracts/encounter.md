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

Every check above has a threshold of **0 violations**. Only checks backed by a database constraint, unique index or trigger are enforced. The rest hold on the seeded data by construction (a few are tested in `tests/test_seed.py`). Nothing measures them on live data yet.

