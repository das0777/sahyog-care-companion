# doctor

| | |
|---|---|
| **Owner** | Scheduling service |
| **Sensitivity** | Operational |
| **Schema version** | 1 (migration 0001) |
| **Notes** | 500 synthetic rows. |

## Checks

- every specialty has at least one doctor
- languages always include en

## Freshness

Daily.

## Consumers, and what breaks for each

Scheduling, W1 shortlist, W3 ownership. If the schema changes: a moved doctor_id breaks encounter ownership checks.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

