# consent

| | |
|---|---|
| **Owner** | Records service |
| **Sensitivity** | Operational, tied to a patient |
| **Schema version** | 1 (migration 0001) |
| **Notes** | Checked on every caregiver read from S4. |

## Checks

- expires_at is in the future for an active consent
- grantee_id never equals patient_id
- scope and purpose are non-empty

## Freshness

Live; expiry checked on every read.

## Consumers, and what breaks for each

W2 scope guard (`can_read`). If the schema changes: a renamed scope or purpose denies every caregiver.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Only checks backed by a database constraint, unique index or trigger are enforced. The rest hold on the seeded data by construction (a few are tested in `tests/test_seed.py`). Nothing measures them on live data yet.

