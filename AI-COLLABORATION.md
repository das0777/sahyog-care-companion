# AI-collaboration log

What the coding agent proposed, what was rejected or changed, and why. One entry per pull request, written when the pull request is merged (house rule 3).

## How this build works

| | |
|---|---|
| **Coding agent** | Claude Code, model Claude Opus 5.5. Every commit carries its `Co-Authored-By` line |
| **Source** | The [MVP](https://github.com/das0777/sahyog-care-companion-mvp), built 27–31 October 2026. Its code, evals and docs are ported here stage by stage, taken from each stage's acceptance tag (`s0-accepted` to `s7-accepted`). Within each pull request, eval cases are committed before the code they test, in the same order as the MVP |
| **Review** | The repo owner reviews each pull request with AI review agents, on GitHub. Each entry below records what that review said, from the pull request's comments. No entry claims a line-by-line human review that didn't happen |
| **CI** | Lint, and a check that the pull request's AI-collaboration note is filled in. The test suite and offline evals need the Docker stack, so they run locally on each branch, and their output is attached to the pull request |
| **What's new compared with the MVP** | Pull requests, recorded reviews, CI, and this log written as the work happens. The MVP's own log of where the agent misled the team is [here](https://github.com/das0777/sahyog-care-companion-mvp/blob/main/AI-COLLABORATION.md) |

## Where the agent misled the team in the MVP

Carried in from the MVP, because these are the lessons this build's reviews look for.

| What the agent got wrong | Check that catches it now |
|---|---|
| Reported that the scrubber kept clinical words intact. It replaced symptoms with name placeholders in 35 of 126 cases, because its test checked only what the scrubber removes, not what it must keep | Gate C22 |
| The same scrubber hid lab test names from the model | Gate F22 |
| Probe 3 wasn't truly blind: the prompt was written after the probe and echoes it | Prompt-overlap tests in W2 and W3. W1 independent recall (C3) still unmeasured |
| Two kill tests proved nothing (job finished before the kill; wrong-patient hold left no chunks) | The third test, a real kill during a 40-page scan |
| A question naming another patient's ID got the caller's own value | Code answers "not found" on another patient's ID |

## Entries

Added as each pull request merges.

### #1 · S0 Foundation

| | |
|---|---|
| **Pull request** | [#1](https://github.com/das0777/sahyog-care-companion/pull/1), ported from the MVP at `s0-accepted` |
| **Review** | An independent AI review agent (Claude, started fresh, no part in writing the code), run by the coding agent at the owner's request. Three rounds, all posted on the pull request. The owner didn't read the code line by line |
| **CI** | Didn't run: GitHub Actions started no workflow runs on this new repo, though it's enabled and both workflows are registered. Lint and tests ran locally on the fixed commit `6f4499f` (`evals/runs/s0-tests.txt`), using the MVP's image with this branch's code mounted |

- **Agent proposed:** the MVP's S0 as it was: Compose stack, 14 tables, database triggers, deterministic seed, dev tokens, audit on every read.
- **Review round 1: changes needed, two must-fix items.**
  - *Lowering a block's capacity left booked tokens above it.* The capacity trigger only checked appointments. **Fixed:** a new trigger on `slot.capacity`, with a test.
  - *The seed comment said "+91 55 ... no real person can ever be texted".* False: +91 55 is outside mobile ranges, but it can match a landline. **Changed:** the claim is corrected in the comment, the test and the patient data contract. **Rejected:** changing the number format, because S1's scrubber tests and egress evals depend on it and nothing in this build sends anything. The reviewer accepted this, on the condition that S2 enforces "never contact a synthetic patient" in code.
- **Review round 2: changes needed, one must-fix item.** A cancelled booking could be reinstated above capacity, because the booking trigger didn't fire on status changes. The reviewer reproduced it on the test database. **Fixed:** the trigger fires on status, skips cancelled rows, and reads capacity `FOR SHARE`, which also closes a race between a booking and a capacity change. A new test runs the reviewer's exact sequence.
- **Review round 3: OK to merge.** The reviewer repeated its reproduction, which is now refused, and tested the race with two live sessions, which is now blocked.
- **Where the agent was wrong:** the MVP's capacity rule had two gaps (capacity changes and reinstated bookings), and one false safety claim in a comment. Both rules had tests, but the tests only covered inserting a booking.
- **Test that catches it now:** `test_capacity_cannot_drop_below_a_booked_token`, `test_cancelled_booking_cant_come_back_above_capacity`. 37 tests pass, 35 before.
- **Recorded risks, fix before real data:** the app connects as the database superuser, which can drop triggers; `TRUNCATE clinical_note` isn't blocked, and the seed truncates it; doctor and desk roles can read any patient; callers set the purpose and trace id that go into the audit; the default dev secret isn't refused at startup; services listen on all interfaces; seeded ABHA IDs are random 14-digit numbers.
- **Carried to S2:** "never contact a synthetic patient", in code with a test. **Also noted:** migration 0001 was edited in place, so an already-migrated database keeps the old triggers until `make reset`. New rules go in new migrations from here on.

### #10 · S1 Safety core and eval harness

| | |
|---|---|
| **Pull request** | [#10](https://github.com/das0777/sahyog-care-companion/pull/10), ported from the MVP at `s1-accepted` on top of the reviewed S0. (#2, the first S1 pull request, was closed unreviewed when the stages were opened all at once by mistake) |
| **Review** | A new independent AI review agent (Claude, fresh, no part in writing the code or in #1's review), run by the coding agent at the owner's request. Three rounds, on the pull request. The reviewer ran its own inputs against the code in the dev image. The owner didn't read the code line by line |
| **CI** | Still not running on this repo. Lint, tests and evals ran locally on the fixed code (`evals/runs/s1-tests.txt`) |

- **Agent proposed:** the MVP's S1 as it was: red-flag rules, scrubber, gateway, offline evals.
- **Review round 1: changes needed, five must-fix items, each shown with a real input.**
  - *Common emergency wordings missed* ("main suicide karna chahta hoon", "मैं मरना चाहता हूं", "baby is not breathing", "my chest hurts", "having a stroke"). B1r showed 30/30 only because the rules were tuned on those probes. **Fixed** with rules for the given wordings, recorded as regression cases, not recall. **Not fixed:** "took 20 paracetamol tablets". The agent argued a count rule would cause false alarms. The reviewer disagreed (the engine already thresholds age) but accepted deferring it to S2 as a fixed rule.
  - *Rule loading didn't fail closed:* an engine with no rules answered "no red flag" to "crushing chest pain". **Fixed:** `RulesNotLoaded`.
  - *Schemas coerced instead of rejecting* (`"0.9"`, `"yes"`), and B7 passed anyway because its fixture couldn't be coerced. **Fixed:** strict schemas.
  - *The system prompt was never scrubbed.* **Changed:** the agent rejected scrubbing it, because it would mangle fixed prompts. The gateway now refuses any outside call whose system prompt carries an identifier. The reviewer accepted.
  - *The known patient's identifiers leaked* (date of birth forms, the name in Devanagari). Date forms **fixed**. Devanagari name **not fixed** (no transliteration library in the image). **Recorded** as a known limitation with a strict expected-failure test, and made an entry condition for S2.
- **Review round 2: changes needed, two items.** The eval run had used the old rules from the shared database, so "all gates pass" was true for the tests but not the evals. **Fixed:** each run now builds its own eval database from the branch. And the Devanagari leak was only in a PR comment. **Fixed:** in the stage doc, with the test.
- **Review round 3: OK to merge.**
- **Where the agent was wrong:** the MVP's S1 rules missed common emergency wordings while its recall gate showed 100%; the gate was fail-open; the schema coerced; a stated contract (scrub everything leaving) wasn't true for the system prompt; and the agent's first rerun claimed evals passed on rules they hadn't loaded.
- **Test that catches it now:** `test_review_wordings_are_caught`, `test_an_engine_with_no_rules_refuses_to_answer`, `test_wrong_types_are_rejected_not_coerced`, `test_system_prompt_with_an_identifier_never_leaves`, the extra date forms in `test_date_of_birth_becomes_an_age_band`, and the strict xfail `test_known_name_in_devanagari_is_not_yet_scrubbed`. 179 passed, 1 expected failure.
- **Carried to S2:** never contact a synthetic patient (from #1); keep Devanagari known-patient prompts in-region or seed a Devanagari name; a fixed "N or more tablets" rule with these wordings as golden cases.
- **Recorded risks, fix before real data:** over-scrubbing of capitalised symptom and test names (the MVP later added C22 and F22); ABHA addresses and landlines leak; B5 is partly circular; no Marathi; Ollama errors escape the fallback; some false alarms and typo misses; the guardrails-off run doesn't cover B6 and B7; no warning when the database holds an older rules version.

### #12 · S3 W2 Ingest

| | |
|---|---|
| **Pull request** | [#12](https://github.com/das0777/sahyog-care-companion/pull/12), ported from the MVP at `s3-accepted` on top of the reviewed S0 to S2 |
| **Review** | A new independent AI review agent (Claude, fresh), run by the coding agent at the owner's request. Three rounds, on the pull request. The reviewer ran a live two-worker overlap on a disposable database. The owner didn't read the code line by line |
| **CI** | Still not running on this repo. Lint, tests and evals ran locally on the fixed code (`evals/runs/s3-tests.txt`) |

- **Agent proposed:** the MVP's W2 ingest: upload, Postgres queue and worker, OCR, identity check, injection scan, local embeddings, patient-filtered search.
- **Review round 1: changes needed, three must-fix items.** The reviewer confirmed that only patients upload, only for themselves, and that nothing leaves the boundary.
  - *The wrong-patient check missed a family member's report:* "Rahul Sharma" passed for "Priya Sharma" on the shared surname, and several label styles were never checked. **Fixed:** every printed name word must match the patient's name, with more labels recognised.
  - *Two workers could run one job:* the 180 s lease was never renewed, and no write checked ownership. **Fixed:** fencing by attempt number on every write, and a lease renewed per page.
  - *A few-KB PDF with one giant page could exhaust the worker's memory.* **Fixed:** pages over A2 are refused, and rendering is capped at 40 MP.
- **Agent's own regression, caught by the eval:** the stricter name check cut "Bakhshi Date" at the stop word "date" and held her report, which also failed D4 and D6. **Fixed** before re-review.
- **Review round 2: changes needed, one item.** The agent's fix held the patient's own report when her name had a title ("Mrs. Priya Sharma"), and no D14 sample had one. **Fixed:** titles are stripped before both checks, whole-word matching applies, text PDFs need a closer word match than scans, and half the D14 samples now print a title.
- **Review round 3: OK to merge.**
- **Where the agent was wrong:** the MVP's identity check and job queue each had a real gap, and no page-size limit; **two of the agent's own fixes in this pull request broke correct reports** (a surname that is a stop word, and a titled name), caught by the eval and by the reviewer.
- **Test that catches it now:** `test_a_family_members_report_is_held` (including titled and longer names), `test_a_worker_that_lost_its_lease_writes_nothing`, `test_a_giant_page_is_refused_at_upload`, and D14 with titled samples. 286 passed.
- **Recorded risks, fix before real data:** search takes `patient_id` from the caller (S4's scope guard must check it, so S4's reviewer is asked to verify); no audit on zero-hit searches; the P-number pattern over-quarantines; D10 checks the chunk's own patient, not the document's; D12 compares 40 characters without collapsing whitespace; no request-body size limit; files left in MinIO when an insert fails; a process-wide PDF lock in the API; keyword candidates without an outer order; the worker can reach the network; "Patient name" without a colon, with the name on the next line, isn't checked; "Mrs.Priya" with no space isn't stripped; D14 samples use only "Smt.".

