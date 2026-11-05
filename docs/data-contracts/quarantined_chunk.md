# quarantined_chunk

| | |
|---|---|
| **Owner** | Records service |
| **Sensitivity** | Identified |
| **Schema version** | 1 (migration 0003) |
| **Notes** | Text flagged by the prompt-injection scan. |

## Checks

- never indexed and never searched

## Freshness

Written by ingest.

## Consumers, and what breaks for each

Desk review. If the schema changes: none at runtime.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

