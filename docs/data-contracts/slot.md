# slot

| | |
|---|---|
| **Owner** | Scheduling service |
| **Sensitivity** | Operational |
| **Schema version** | 1 (migration 0001) |
| **Notes** | A booking block with capacity, not a single appointment (E2.4). |

## Checks

- capacity > 0
- ends_at > starts_at
- blocks start inside clinic hours
