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

Compliance queries. If the schema changes: compliance queries that name columns break, and the append-only triggers must be re-created for any new table.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Only checks backed by a database constraint, unique index or trigger are enforced. The rest hold on the seeded data by construction (a few are tested in `tests/test_seed.py`). Nothing measures them on live data yet.

