# prescription

| | |
|---|---|
| **Owner** | Scribe service |
| **Sensitivity** | Clinical |
| **Schema version** | 1 (migration 0001) |
| **Notes** | Dose comes only from the doctor. |

## Checks

- every medicine_id appears in the transcript (checked in S5)

## Freshness

Written at signature.

## Consumers, and what breaks for each

Pharmacy. If the schema changes: medicine_id may be UNLISTED; consumers must handle it.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Only checks backed by a database constraint, unique index or trigger are enforced. The rest hold on the seeded data by construction (a few are tested in `tests/test_seed.py`). Nothing measures them on live data yet.

