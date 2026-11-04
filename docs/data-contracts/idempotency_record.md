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
