# specialty

| | |
|---|---|
| **Owner** | Scheduling service |
| **Sensitivity** | Operational |
| **Schema version** | 1 (migration 0001) |
| **Notes** | 38 rows; red_flag_rules feed the S1 rule engine. |

## Checks

- name unique
- red_flag_rules.global is non-empty
- reviewed_by is null until a clinician signs off
