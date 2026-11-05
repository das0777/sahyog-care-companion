# desk_ticket

| | |
|---|---|
| **Owner** | Scheduling service |
| **Sensitivity** | Identified: `patient_text` holds the patient's own words |
| **Schema version** | 1 (migration 0002) |
| **Notes** | Work for the front desk. Queue order: priority 0 first, then oldest first (E2.5). |

## Checks

- kind is one of `er`, `safety_unchecked`, `low_confidence`, `advice_request`, `no_availability`, `model_failure`, `ai_booking`, `late_block`
- one ticket per thread and kind, per appointment and kind, and per late block
- `patient_text` is blanked 30 days after the ticket closes
- never leaves the hospital boundary

## Freshness

Live.

## Consumers, and what breaks for each

Desk queue. If the schema changes: kind or status values change breaks the queue order.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

