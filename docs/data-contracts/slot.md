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

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

