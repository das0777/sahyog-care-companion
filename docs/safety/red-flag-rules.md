# Red-flag rules

The W1 gate's rules live in `sahyog/seed/red_flags.yaml`, are seeded into `Specialty.red_flag_rules`,
and are read from the database at run time. They are a starter list written by Claude, **not
clinical guidance**. `reviewed_by` stays `null` until a Sahyog clinician signs them off.

## What a rule looks like

| Part | Fires on its own? | Example |
|---|---|---|
| **concept** | Yes | `chest_pain`: "chest pain", "seene mein dard", "सीने में दर्द" |
| **signal** | No, only inside a combo | `breathless`, `fever`, `pregnant` |
| **modifier** | No; a condition on a combo | `age_40_plus` (from the text or the profile), `diabetic` |
| **combo** | Yes, when every group matches and any required modifier holds | `cardiac_pattern`: arm or jaw pain + breathless or sweating + age ≥ 40, diabetes, hypertension or smoking |

## How matching works

- Text is lower-cased and normalised (the Devanagari nukta and chandrabindu are unified).
- Synonyms of 7+ characters tolerate one typo per word ("chest pian") and one inserted word
  ("pain in the chest"). Shorter synonyms must match exactly.
- A synonym starting with `=` is always exact. Use it for phrases one letter away from everyday
  words: `=marna chahta` (want to die) vs "karna chahta" (want to do).
- Negation is **not** handled, on purpose: "no chest pain" flags. See ADR 0002.

## Changing the rules

1. Add the failing phrase to `evals/w1/golden.jsonl` first, with `source` and `author`.
2. Change `red_flags.yaml` and bump `version`.
3. `make seed`, then `make eval` and `make test`: recall must stay 100%, and the false-alarm count
   (B3) should not grow without a reason written in the pull request.
4. A clinician reviews the pull request and, once signed off, sets `reviewed_by`.

Try any wording with `make redflag text="…"`.
