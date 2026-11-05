# idempotency_record

| | |
|---|---|
| **Owner** | API |
| **Sensitivity** | Identified: holds the first reply to a write |
| **Schema version** | 1 (migration 0002) |
| **Notes** | The same key returns this reply; the key with a different body gets 409. |

## Checks

- unique on actor and key
- deleted after 30 days

## Freshness

Live; replays return the first answer.

## Consumers, and what breaks for each

API retries. If the schema changes: key format change lets a retry act twice.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Only checks backed by a database constraint, unique index or trigger are enforced. The rest hold on the seeded data by construction (a few are tested in `tests/test_seed.py`). Nothing measures them on live data yet.

