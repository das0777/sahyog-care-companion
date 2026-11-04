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

### #13 · S4 W2 Ask

| | |
|---|---|
| **Pull request** | [#13](https://github.com/das0777/sahyog-care-companion/pull/13), ported from the MVP at `s4-accepted` on top of the reviewed S0 to S3. One manual merge in `tests/test_deid.py` |
| **Review** | A new independent AI review agent (Claude, fresh), run by the coding agent at the owner's request. Three rounds, on the pull request. **The owner merged after round 2's fixes were pushed but before round 3's verdict**; round 3 then said OK to merge. This entry is written afterwards, in the next pull request, because #13's branch was closed |
| **CI** | Still not running (GitHub also had an outage affecting git operations and pull requests during this review). Lint, tests and evals ran locally (`evals/runs/s4-tests.txt`) |

- **Agent proposed:** the MVP's W2 ask: scope guard, red-flag gate, retrieval, answer citing excerpts, safety check in code.
- **Carried from S3, verified:** `retrieve_records` takes `patient_id` from its caller. The reviewer confirmed its only S4 caller runs after `scope_guard`'s `can_read`, and that nothing streams before the safety check.
- **Review round 1: changes needed, two must-fix items.**
  - *The diagnosis and dose refusal was switched off by everyday words* ("the", "was", "report"): "what dose of the metformin should I take" and "do I have diabetes, check my report" went to the model. **Fixed:** a forward-looking question is advice however it mentions the report.
  - *The code-side answer check missed most interpretation and dose-change wording* ("is low", "which is high", "Increase Metformin", "You can stop", Hindi). **Fixed.**
- **Review round 2: changes needed.** Hinglish and Hindi judgements, Hinglish dose changes, reassurance ("is normal", "nothing to worry about") and a stop/start rule for questions were still missing. **Fixed.**
- **Review round 3: OK to merge.** 51 of 51 earlier inputs correct, 22 of 29 new ones. **The reviewer advised stopping the phrase chase:** each round fixed the exact inputs given, and new rewordings still slip through. The word lists are a backstop behind the model's diagnosis-or-dose flag. Its 7 misses are now expected-failure tests (`test_s4_backstop_misses`), S4's stage doc says the lists are a backstop, and **S7 must measure them in both directions on rewordings nobody has seen.**
- **Where the agent was wrong:** the MVP's refusal had a fail-open read-back exception, and its answer check covered only a narrow set of phrases; its tests only used phrases the checks already caught.
- **Test that catches it now:** `test_advice_wrapped_in_report_words_is_still_refused`, `test_a_read_back_question_still_goes_on`, `test_interpretation_and_dose_changes_are_blocked`, `test_a_plain_read_back_is_not_blocked`. 362 passed.
- **Recorded risks, fix before real data:** the number check compares sets (a swapped value and range pass; "1,000" against "1,50,000"; number words unchecked); `guardrails=False` also disables `can_read` (eval-only, but authorisation shouldn't depend on it); the crash ticket uses the request body's patient_id; the patient-ID pattern is case-sensitive; F16o is hard-coded under guardrails-off; F17 doesn't check the Devanagari name; **the live and red-team results are from the MVP (2026-10-30) and weren't re-run on this graph**, because there's no model key in this build; the checks are too strict in a few read-back cases (a desk ticket, not a wrong answer).

### #14 · S5 W3 Consultation scribe, and its follow-up

| | |
|---|---|
| **Pull requests** | [#14](https://github.com/das0777/sahyog-care-companion/pull/14), ported from the MVP at `s5-accepted` on top of the reviewed S0 to S4; its first commit carried S4's follow-ups (#13's log entry and backstop tests). The follow-up pull request that holds this entry closes what #14 left open |
| **Review** | A new independent AI review agent (Claude, fresh), run by the coding agent at the owner's request. Four rounds on #14. The reviewer ran crafted inputs through the grounding functions and the `draft_soap` node. The owner didn't read the code line by line |
| **Merge** | **The owner merged #14 at 11:38 UTC on head `3ac3f34`, while round 4 said "changes needed" with two must-fix items open.** Their fix (`7e8e6d0`, re-applied as `1200d19`) was already written and tested but not pushed. It arrives in the follow-up pull request, and the same reviewer checks it there |
| **CI** | Still not running on this repo. Lint, tests and evals ran locally (`evals/runs/s5-tests.txt`) |

- **Agent proposed:** the MVP's W3: transcribe, draft the SOAP note, ground medicines against the transcript, flag stock, interrupt for the doctor's signature, store the note immutably.
- **What held from round 1:** only the encounter's doctor can resume or sign; there's a per-thread lock; a signed thread returns 423; database triggers block changes to signed notes; the worker never reaches `store`.
- **Round 1: changes needed, five must-fix items, all about something the doctor didn't say reaching a signed note.**
  - *A dose matched anywhere in the dictation:* "amlodipine 25 mg" kept the model's 5 mg; route and frequency were never checked. **Fixed:** the dose, route and frequency must sit beside their own medicine.
  - *Fuzzy names and no negation:* "valsartan" passed for "losartan", and "Do not give metformin 500 mg" became a prescription. **Fixed:** names are whole words, and negation is checked.
  - *A SOAP line's text was never compared with its quote:* "Start apixaban 5 mg", "Ecosprin 75" and "fifty mg" survived. **Fixed:** a line that adds to its quote becomes the quote.
  - *The edit path skipped the gap rule:* a medicine with no dose could be signed, and an edit could clear an open gap. **Fixed.**
  - *Evals that couldn't fail:* G3o's invented drug was on the code's own list. **Fixed:** apixaban.
- **Round 2: changes needed, three must-fix items.** Quotes were matched fuzzily ("non diabetic" stood for "known diabetic", the patient's age gave "50 mg"); the dose window ran past unlisted drugs; negation after the name was missed. The agent's own round-1 negation rule was also dropping real prescriptions ("No change, continue metformin"). **Fixed:** exact quotes, clause-bounded windows, and after-name phrases.
- **Round 3: changes needed, two must-fix items.** A SOAP line could *drop* a negation ("Start metformin" for "do not start metformin"); negation phrase lists kept missing forms. **Fixed with the reviewer's suggestion:** any negation in a medicine's sentence makes it a gap the doctor confirms or removes. The code doesn't guess.
- **Round 4: changes needed, two must-fix items. Open when #14 merged.** The agent's round-3 change (a comma no longer ends a medicine's instruction) let a dose leak from a following brand ("amlodipine 5 mg, Telma 40 mg" gave Amlodipine 40 mg), and the two negation lists disagreed ("continue" for "discontinue"; "withhold", "cease", "skip" unknown). **Fixed in the follow-up:** only the first dose after a name counts, one shared negation list with inflected forms, and "2.5 mg" is no longer split.
- **Where the agent was wrong:** the MVP's grounding let unsaid doses, near-miss names, negated drugs and added drugs reach a signed note, and its evals couldn't show it. **Three of the agent's own fixes introduced new gaps** (a negation rule that dropped real prescriptions; a comma change that leaked doses; two lists that drifted apart), each caught by the reviewer's new inputs.
- **Test that catches it now:** in `tests/test_scribe.py`, `test_a_dose_must_sit_beside_its_own_medicine`, `test_a_similar_or_misspelled_name_is_not_the_doctors`, `test_a_negated_medicine_is_not_prescribed`, `test_a_soap_line_cant_add_to_its_quote`, `test_a_quote_must_be_the_doctors_exact_words`, `test_a_line_cant_drop_a_negation_its_quote_holds`, `test_a_negation_anywhere_in_the_sentence_makes_the_doctor_confirm`, `test_a_real_prescription_near_a_negation_is_kept_for_the_doctor`, `test_a_dose_cant_come_from_the_next_drug_in_the_sentence`, `test_a_line_cant_reverse_the_doctor`, `test_withhold_cease_and_skip_make_the_doctor_confirm`, `test_a_decimal_dose_isnt_split_at_its_point`, and the edit-path tests. 422 passed and 7 expected failures on the follow-up.
- **Recorded risks, fix before real data:** a second transcript is allowed on an already-signed encounter; two threads per encounter can both sign; the transcript panel is collapsed and nothing makes the doctor read it, which is the only defence against a misheard "NON diabetic"; the audio sweep keys on the encounter's start, and a re-upload after a sweep is never swept; a 180 s lease is short for CPU transcription; stored transcripts have no retention limit; the drug-class list is narrow ("antiemetic", "inhaler"); G7 resumes the graph directly rather than through the API; G12 checks only the Latin name.

