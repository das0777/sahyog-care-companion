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
