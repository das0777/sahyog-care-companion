# slot

| | |
|---|---|
| **Owner** | Scheduling service |
| **Sensitivity** | Operational |
| **Schema version** | 1 (migration 0001) |
| **Notes** | A booking block with capacity, not a single appointment (E2.4). |

## Checks

- capacity > 0
- ends_at > starts_at
- blocks start inside clinic hours

## Freshness

Generated 14 days ahead; capacity changes live.

## Consumers, and what breaks for each

W1 booking, desk, MCP. If the schema changes: capacity semantics change breaks the capacity triggers.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Only checks backed by a database constraint, unique index or trigger are enforced. The rest hold on the seeded data by construction (a few are tested in `tests/test_seed.py`). Nothing measures them on live data yet.

