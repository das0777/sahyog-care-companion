# patient

| | |
|---|---|
| **Owner** | Records service |
| **Sensitivity** | Direct identifiers |
| **Schema version** | 1 (migration 0001) |
| **Notes** | Never leaves the boundary; tokenised before any external call. |

## Checks

- patient_id unique, format P + 4 digits
- name_local: the name in Devanagari, optional; synthetic rows get an independent Faker hi_IN name
- abha_id unique, format NN-NNNN-NNNN-NNNN
- phone in +91 55 range while synthetic. That's outside India's mobile ranges (6 to 9), but it can match a real landline, so **no SMS or call adapter may contact a patient with synthetic = true**
- synthetic = true for every seeded row

## Freshness

Seeded; in production, synced from the HIS daily.

## Consumers, and what breaks for each

W1, W2, W3, scrubber (identity), desk. If the schema changes: a renamed column fails loudly in `KnownIdentity.from_patient`; **a new identifier column that isn't added there is never scrubbed, and leaks silently**.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Only checks backed by a database constraint, unique index or trigger are enforced. The rest hold on the seeded data by construction (a few are tested in `tests/test_seed.py`). Nothing measures them on live data yet.

