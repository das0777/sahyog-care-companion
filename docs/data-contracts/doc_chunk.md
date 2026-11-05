# doc_chunk

| | |
|---|---|
| **Owner** | Records service |
| **Sensitivity** | Clinical |
| **Schema version** | 1 (migration 0001) |
| **Notes** | patient_id is copied from the document so retrieval filters in SQL (E4.2). |

## Checks

- patient_id equals its document's patient_id
- embedding has 1,024 dimensions once indexed
- page >= 1

## Freshness

Written by ingest; replaced on a fenced retry.

## Consumers, and what breaks for each

W2 search. If the schema changes: dropping patient_id breaks the patient filter: cross-patient reads.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

