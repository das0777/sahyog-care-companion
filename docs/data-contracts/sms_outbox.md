# sms_outbox

| | |
|---|---|
| **Owner** | Scheduling service |
| **Sensitivity** | Operational, tied to a patient |
| **Schema version** | 1 (migration 0002) |
| **Notes** | SMS stub. A template and its variables; nothing is sent until a real gateway replaces it. |

## Checks

- template is a known template, never free text

## Freshness

Live; never sent in this build.

## Consumers, and what breaks for each

`notify.deliver` (refuses synthetic patients). If the schema changes: none until a sender exists.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Only checks backed by a database constraint, unique index or trigger are enforced. The rest hold on the seeded data by construction (a few are tested in `tests/test_seed.py`). Nothing measures them on live data yet.

