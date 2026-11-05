# audit_event

| | |
|---|---|
| **Owner** | Platform |
| **Sensitivity** | Operational |
| **Schema version** | 1 (migration 0001) |
| **Notes** | Append-only and kept one year; answers "who saw this record?" (E6.1). |

## Checks

- never updated, deleted or truncated (triggers)
- outcome in allowed, denied
- one row per patient-scoped read, including denials

## Freshness

Append-only by trigger.

## Consumers, and what breaks for each

Compliance queries. If the schema changes: any UPDATE, DELETE or TRUNCATE is refused by trigger.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

