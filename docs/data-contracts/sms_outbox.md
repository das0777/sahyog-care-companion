# sms_outbox

| | |
|---|---|
| **Owner** | Scheduling service |
| **Sensitivity** | Operational, tied to a patient |
| **Schema version** | 1 (migration 0002) |
| **Notes** | SMS stub. A template and its variables; nothing is sent until a real gateway replaces it. |

## Checks

- template is a known template, never free text
