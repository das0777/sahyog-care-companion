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

Every check above has a threshold of **0 violations**. Only checks backed by a database constraint, unique index or trigger are enforced. The rest hold on the seeded data by construction (a few are tested in `tests/test_seed.py`). Nothing measures them on live data yet.

