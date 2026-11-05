# appointment

| | |
|---|---|
| **Owner** | Scheduling service |
| **Sensitivity** | Operational, tied to a patient |
| **Schema version** | 1 (migration 0001) |
| **Notes** | Unique on idempotency_key and on (slot_id, token_no); a trigger keeps token_no within capacity (E2.3). |

## Checks

- token_no between 1 and the block's capacity
- status in booked, checked_in, in_consult, done, cancelled, no_show
- consult_ended_at after consult_started_at when both set

## Freshness

Live.

## Consumers, and what breaks for each

W1, desk, W3 encounters, audit. If the schema changes: status values change breaks the active-booking index and triggers.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

