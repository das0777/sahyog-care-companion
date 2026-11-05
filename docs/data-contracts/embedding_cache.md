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

Every check above has a threshold of **0 violations**. Only checks backed by a database constraint, unique index or trigger are enforced. The rest hold on the seeded data by construction (a few are tested in `tests/test_seed.py`). Nothing measures them on live data yet.

