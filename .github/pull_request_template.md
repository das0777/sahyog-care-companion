## What this changes

<!-- One or two sentences. Name the stage or story (for example E3.2). -->

## AI collaboration

House rule 3: every pull request carries this note. The check fails if a field is left empty.

**Agent proposed:**
<!-- What the coding agent suggested or wrote. -->

**Rejected or changed, and why:**
<!-- What you turned down or rewrote, and the reason. "Nothing" is an answer, but say why. -->

**Where the agent was wrong:**
<!-- A wrong claim, a bug, a test that proved nothing. "Nothing found" is an answer. -->

**Test that catches it now:**
<!-- Test name or eval case id. New surprises go into the eval set the same day (rule 10). -->

**What I checked myself:**
<!-- Diff read against the PHI checklist? Ran it? Wrote my own test cases? -->

## Checks

- [ ] Eval cases for this change were committed before the code
- [ ] `make test` and `make eval` pass, and `make eval GUARDRAILS=off` fails
- [ ] No real patient data, secrets or `.env` in the diff
