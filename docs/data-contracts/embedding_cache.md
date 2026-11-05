# embedding_cache

| | |
|---|---|
| **Owner** | Records service |
| **Sensitivity** | Operational |
| **Schema version** | 1 (migration 0003) |
| **Notes** | Vectors by content hash, so a re-uploaded report isn't embedded twice. |

## Checks

- holds no text; keyed on hash and model

## Freshness

Content-addressed; never stale.

## Consumers, and what breaks for each

Ingest. If the schema changes: model change needs the model column checked.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

