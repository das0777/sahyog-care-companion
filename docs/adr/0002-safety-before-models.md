# ADR 0002 · Safety runs before models, and models cannot overrule it

| | |
|---|---|
| **Status** | Accepted for S1 |
| **Date** | 2026-10-30 |

## Context

The PRD treats a missed emergency and a leaked identifier as release-blocking. Both have to hold
even when a model is wrong, slow or unavailable, and they have to be shown with numbers before
any agent graph exists.

## Decision

1. **The red-flag gate is deterministic and runs first.** Rules are data in
   `Specialty.red_flag_rules`, matched as concepts (synonyms in English, Hinglish and Devanagari),
   with typo tolerance and combination rules. A model's second pass can only add flags.
2. **Fail safe on negation.** "No chest pain" still flags. False alarms are measured (B3) and are
   the price of never cancelling a flag on wording the rules misread.
3. **Every model call goes through one gateway.** No vendor SDK is imported anywhere else; a lint
   rule (`TID251`) and a test enforce this. The gateway scrubs before anything leaves the hospital
   boundary, validates the reply against a schema, and re-identifies only after validation.
4. **Reject, never repair.** A reply that does not match its schema raises `SchemaRejected`. It is
   not retried or patched, because repairing hides model errors and can invent fields.
5. **In-region work never falls back outside the boundary.** A call that must keep identifiers
   fails closed (`BoundaryViolation`) rather than reach a provider outside India.
6. **Evals prove the guardrails.** `make eval GUARDRAILS=off` must fail; a passing eval with the
   guardrails off would mean the eval tests nothing.

## Consequences

- W1 shows some false emergency hand-offs; the desk queue (S2) absorbs them.
- Rules need clinician review before any real use; until then `reviewed_by` stays null.
- The scrubber is deterministic and inspectable, but it over-scrubs some proper nouns (clinic and
  place names written as capitalised pairs). Clinical content is measured separately (B6).
