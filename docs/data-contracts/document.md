# document

| | |
|---|---|
| **Owner** | Records service |
| **Sensitivity** | Clinical |
| **Schema version** | 1 (migration 0001) |
| **Notes** | uri points to the object store; status is visible to the patient (E3.1). |

## Checks

- status in queued, parsed, indexed, failed
- every row belongs to an existing patient

## Freshness

Live, per upload.

## Consumers, and what breaks for each

W2 ingest and ask, audit. If the schema changes: status values change breaks the ingest status screen.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

