# audit_event

| | |
|---|---|
| **Owner** | Platform |
| **Sensitivity** | Operational |
| **Schema version** | 1 (migration 0001) |
| **Notes** | Append-only and kept one year; answers "who saw this record?" (E6.1). |

## Checks

- never updated, deleted or truncated (triggers)
- outcome in allowed, denied
- one row per patient-scoped read, including denials
