# ingest_job

| | |
|---|---|
| **Owner** | Records service |
| **Sensitivity** | Operational, tied to a patient |
| **Schema version** | 1 (migration 0003) |
| **Notes** | One upload's trip through the worker. Postgres is the queue. |

## Checks

- attempts never exceed 3; a job with an expired lease can be claimed by another worker

## Freshness

Live queue; leased and fenced by attempt.

## Consumers, and what breaks for each

Worker, upload status. If the schema changes: attempt or lease columns change breaks fencing: duplicate chunks.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

