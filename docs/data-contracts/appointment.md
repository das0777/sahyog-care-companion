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
