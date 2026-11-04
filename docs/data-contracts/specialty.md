# specialty

| | |
|---|---|
| **Owner** | Scheduling service |
| **Sensitivity** | Operational |
| **Schema version** | 1 (migration 0001) |
| **Notes** | 38 rows. `red_flag_rules` is the red-flag gate's rule set, seeded from `sahyog/seed/red_flags.yaml` (see `docs/safety/red-flag-rules.md`). |

## Checks

- name unique
- red_flag_rules has `version`, `reviewed_by`, `global` (concepts, signals, modifiers, combos) and `specific` (this specialty's concepts)
- red_flag_rules.global.concepts is non-empty, and every row carries the same `version`
- every combo names only signal or concept ids that exist
- reviewed_by is null until a clinician signs off
