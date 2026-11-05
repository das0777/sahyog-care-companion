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

## Freshness

Changes with the catalogue; rules versioned (`version:` in red_flags.yaml).

## Consumers, and what breaks for each

W1 match and red-flag gate. If the schema changes: empty or old rules: the gate refuses to answer (RulesNotLoaded), so triage goes to the desk.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Only checks backed by a database constraint, unique index or trigger are enforced. The rest hold on the seeded data by construction (a few are tested in `tests/test_seed.py`). Nothing measures them on live data yet.

