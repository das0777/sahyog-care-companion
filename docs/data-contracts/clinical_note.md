# clinical_note

| | |
|---|---|
| **Owner** | Scribe service |
| **Sensitivity** | Clinical |
| **Schema version** | 1 (migration 0001) |
| **Notes** | Immutable once signed; edits create a new version (E5.2). |

## Checks

- a signed row is never updated or deleted (trigger)
- (encounter_id, version) unique
- hash present when signed_at is set

## Freshness

Immutable once signed.

## Consumers, and what breaks for each

Doctors, pharmacy read, audit. If the schema changes: the immutability trigger depends on signed_at.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

