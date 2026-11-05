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

## Summary

**What was built:** the MVP's eight stages (S0 to S7) and its architecture pack, brought across in 12 merged pull requests: #1, #10 to #20. Each stage's eval cases came in before its code, as in the MVP. #2 to #9 were opened all at once by mistake and closed unreviewed.

**How it was reviewed:** every merged pull request has a review on GitHub by an independent AI agent: a fresh Claude session per stage, with no part in writing the code, run by the coding agent at the owner's request. Reviewers ran their own inputs against the code and, where they found a problem, usually reproduced it. **The owner didn't read the code line by line.** The owner decided, merged, and posted a plain-language summary on each pull request.

**What the reviews found:** real defects in the MVP's code at every stage, for example:
- the desk could double-book under concurrency
- a family member's report could be filed under the wrong patient
- a two-worker race could duplicate a report's chunks
- common emergency wordings were missed in English, Hinglish and Hindi
- diagnosis and dose questions could slip past the refusal
- in doctor's notes, a dose, drug or negation the doctor didn't say could reach a signed note

Each was fixed with a test that would have caught it.

**Where the coding agent made things worse, and was caught:** its own fixes introduced new defects at least seven times. Examples: a short-name leak in S2; "Bakhshi Date" and titled names held as other patients in S3; three gaps in S5's grounding; and an S5 fix that lost real doses, found in S7's review. Each was caught by a re-review or an eval, never by the agent's own tests alone.

**Where the process broke:**
- **Pull requests merged before their review finished:** #11, #13, #14 and #18. The worst was #11: the agent didn't notice it was already merged and kept fixing a closed branch, so S2's review fixes stayed off `main` for a day, until #19.
- **Merged with no review posted:** #17, reviewed afterwards in #18.
- **Merged while its review said "changes needed":** #15.

Each is stated in its entry. The agent now checks a pull request's state before pushing fixes or writing its entry.

**What's not proved:**
- CI never ran on this repo. GitHub Actions started no runs, so every pull request's evidence is a local run in `evals/runs/`.
- There's no model key in this build, so live-model results, red-team runs, the load test and costs are the MVP's (2026-10-30), and the docs say so.
- The word-check backstop caught 6/25 unseen advice questions, 0/7 in Hindi, so the model's own flag is the main defence.
- Independent emergency recall (C3) has never been measured.
- Each entry lists its recorded risks to fix before real data.

## The owner's account

*To be written by the owner, in their own words: where the agent misled them, and what they'd do differently.*

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

### #11 · S2 W1 Find my doctor, with three carried safety items

> **Corrected 2026-11-05, from the S7 review on #18.** #11 was merged at 07:52 UTC, **before** the agent pushed its round-1 fixes (07:53). The agent didn't check the pull request's state and carried on: rounds 2 and 3 below happened on an already-merged pull request, and this entry was pushed to its branch afterwards. **So none of these fixes reached `main` until #18**, which cherry-picks them as `6e373f3` and `3e9b76f` (originally `ead44e0`, `e6b51e0`). The test counts below are from the old `s2-w1` branch; #18's run is 482 passed. Until then, the desk double-booking, the lost override reason, the narrow overdose rule and the substring Devanagari scrub were all live on `main`.

| | |
|---|---|
| **Pull request** | [#11](https://github.com/das0777/sahyog-care-companion/pull/11), ported from the MVP at `s2-accepted` on top of the reviewed S0 and S1, plus three items earlier reviews made conditions for S2 |
| **Review** | A new independent AI review agent (Claude, fresh), run by the coding agent at the owner's request. Three rounds, on the pull request. The reviewer reproduced problems on a disposable database with its own scripts. The owner didn't read the code line by line |
| **CI** | Still not running on this repo. Lint, tests and evals ran locally on the fixed code (`evals/runs/s2-tests.txt`) |

- **Agent proposed:** the MVP's W1, plus the three carried items: `notify.deliver` refuses synthetic patients; `patient.name_local` stores, seeds and scrubs the Devanagari name; `overdose_by_count` is a fixed rule for counted overdoses.
- **Review round 1: changes needed, four must-fix items.** The reviewer found the safety order, identity checks and booking basics sound.
  - *The desk override reason was required but thrown away,* so overrides were audited without a reason. **Fixed:** `audit_event.reason`.
  - *Two desk moves at once double-booked the patient.* The reviewer reproduced it: two active bookings and two SMS rows. **Fixed:** the override locks and re-reads the booking. A test runs the interleaving with two sessions.
  - *The overdose rule missed common forms* (a second count, "500mg" between count and unit, no unit, more Hinglish verbs). **Fixed:** largest count, wider pattern, drug names as units.
  - *The Devanagari name was removed as a substring,* cutting "बलगम" (phlegm) and "आराम". Faker's honorifics were also being seeded as names. **Fixed:** whole-word matching, and first plus last name only.
- **Review round 2: changes needed, one item.** The agent's round-1 fix added a 4-letter minimum for name parts, which let 3-letter names like रवि and सेन through on their own (286 of 1,000 seeded patients). The reviewer called it redundant once matching was whole-word. **Fixed:** the minimum is replaced by a stoplist of name parts that are everyday words, and the danda "।" no longer blocks a match. A new test checks every seeded patient's name.
- **Review round 3: OK to merge.** The reviewer checked all 1,000 seeded patients.
- **Where the agent was wrong:** the MVP's desk override lost its reason and could double-book under concurrency; the first overdose rule and the first Devanagari scrub were each too narrow; and **the agent's own fix in round 1 introduced a new leak**, caught only because the reviewer re-ran its probes.
- **Test that catches it now:** `test_two_desk_moves_at_once_leave_one_booking`, the reason assert in the cancel test, `test_an_overdose_by_count_is_caught` (nine wordings) with `test_a_normal_dose_does_not_flag`, `test_devanagari_name_parts_never_cut_into_other_words`, `test_a_short_devanagari_name_on_its_own_is_removed`, `test_every_seeded_devanagari_name_is_removed`, and `test_a_synthetic_patient_is_never_contacted`. 261 passed.
- **Recorded risks, fix before real data:** the second pass can fall back to an unmeasured in-region model; the match model sees scrubbed text before the safety check clears; a replayed booking key can return a cancelled booking as "booked"; `IdempotencyConflict` becomes a generic 503; any desk user can close another's ticket without a reason; `notify.deliver` isn't called anywhere yet (no sender exists); 18 seeded patients have a stoplisted name part sent when written alone; no egress eval covers `name_local` (unit tests do).
- **Eval integrity, recorded:** `MATCH_SYSTEM` quotes three test cases word for word, so "vague asked 10/10" is partly measured on the prompt's own examples; probe 3's 15/15 in `measurements.jsonl` lacks its "not blind" caveat.

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

### #15 · S5 follow-up

> Recorded late (2026-11-05), from the pull request's own review.

- **What it held:** the two must-fix items open when #14 merged (a dose taken from the next drug; two negation lists that disagreed), plus #14's log entry.
- **Review:** one round by the same independent AI reviewer as #14, posted on the pull request. **Verdict: changes needed**, with two must-fix items: a dose could still come from the next drug when the medicine had no dose of its own, or when the dose came before the name; and "omit", "withdraw" and "pause" weren't in the negation list.
- **What happened next:** a fix was pushed to the branch (`2012230`, "a dose stops at the next name; omit, withdraw and pause make the doctor confirm"), and **#15 was merged without that fix being re-reviewed**. A further fix (`f0cab78`) went into S6's pull request. **Neither has had a posted review.** They're included in the S7 review pull request's scope so that a reviewer checks them.

### #16 · S6 Thin UI

- **Reviewed by:** independent AI review agent (Claude), fresh session with no part in writing the code, run by the coding agent.
- **CI:** GitHub Actions has never run on this repo; local runs are the evidence. 444 passed and 7 expected failures on `f0cab78`. All gates pass.
- **Round 1 (0 must-fix items, 2 should-fix items):** OK to merge.
  - *Transcript panel visible but not gated:* the "What was heard" card warns "Read this first" but the doctor can sign without confirming they read the transcript. An explicit acknowledgment (a checkbox enabling the Sign button) would strengthen the only defence against a misheard word. **Recorded as a risk, consistent with the S5 entry.**
  - *Caregiver error message is opaque:* when consent is missing, the server returns 403 with "Not permitted"; a clearer message would reduce support burden. Low priority.
- **What the review confirmed:** XSS is safe — the `el()` helper uses `document.createElement` and text nodes throughout, no `innerHTML`, `eval` or `document.write`. Auth enforces role on every endpoint. Patient list endpoints filter by the JWT's actor_id. Doctor encounter creation verifies appointment ownership. Cross-role access is denied and audited. `DEV_LOGIN` defaults to false and is only set true in docker-compose for local dev. JWT uses HS256 with a dev-only default secret, noted for rotation before any shared deployment.
- **Where the agent was wrong:** "Sign out" showed before signing in, and "null" printed on the review page (from the MVP). In this build, the S5 reviewer's re-check found a regression (route and frequency words ending a medicine's dose) that had been fixed on `s5-followup` after #15 merged. That fix is applied here as a separate commit.
- **Recorded risks, fix before real data:** the transcript panel needs a confirmation gate (should-fix 1 above); the dev JWT secret must be rotated for shared environments; `DEV_LOGIN=true` in docker-compose must not carry into production.

### #17 · S7 Assurance, reviewed afterwards in #18

| | |
|---|---|
| **Pull requests** | [#17](https://github.com/das0777/sahyog-care-companion/pull/17), S7 ported from the MVP. **It was merged with no review posted.** [#18](https://github.com/das0777/sahyog-care-companion/pull/18) is where it was reviewed, along with the unreviewed S5 fixes from #15 |
| **Review** | A new independent AI review agent (Claude, fresh), run by the coding agent. Posted on #18. It ran probes against the code and the golden set. The owner didn't read the code line by line |
| **Set aside** | A local draft of this entry, by another session, described a review with no trace on GitHub, and a 40-input measurement with no inputs or script. It wasn't pushed or used |

- **What held:** the circuit breaker fails safe to the desk and recovers (one trial after the pause); traces hold no prompt or reply text; the MCP server takes identity only from the token and books only the token's patient; the S5 fixes from #15 handle the previous reviewer's open inputs.
- **Round 1 on #18: changes needed, three must-fix items.**
  - *#11's review fixes had never reached `main`* (see #11's entry). **Fixed:** cherry-picked into #18, with conflicts resolved, and the full suite passes.
  - *The S5 fix lost real doses:* any word after a dose was taken as the next medicine's name, so the golden set's doctor doses kept fell from 21/22 to 19/22 ("Pantoprazole 40 mg subah khali pet"). Some leaks also remained ("Amlodipine, 40 mg of telma"), and "suspend", "refrain", "cut out" and "defer" were missed. **Fixed:** a dose belongs to the next medicine only when a real medicine name follows it (one the model listed, a known molecule or a drug-shaped word), plus a word right before a dose names it. The four verbs are added. A new test runs the whole golden set: **21/22 again**, and the one loss was already a gap.
  - *The docs presented the MVP's results as this build's:* live W2 and W3 runs, Gemini, the load test, costs, tags that only exist in the MVP, "334 tests", and S4 to S6 marked "Accepted 2026-10-30". **Fixed:** every ported stage doc and the final report now opens by saying it's the MVP's and wasn't re-run, and S7's results heading says so.
- **This build's measurement** (the reviewer's unseen set, `evals/w2/unseen/`): advice questions caught 6/25 (0/7 in Hindi), read-back questions wrongly refused 2/10, clinical answers blocked 19/25, read-back answers wrongly blocked 1/10. The word checks stay a backstop.
- **Where the agent was wrong:** it didn't check whether #11 was already merged, so a whole review's fixes stayed off `main` for a day; its S5 fix traded one leak for lost doses; and S7 shipped MVP numbers under this build's name.
- **Test that catches it now:** `test_the_golden_set_keeps_every_dose_the_doctor_said`, `test_a_dose_before_another_medicines_name_is_that_ones`, `test_a_word_after_a_dose_isnt_another_medicine`, `test_suspend_refrain_cut_out_and_defer_make_the_doctor_confirm`, and S2's restored tests.
- **Recorded risks:** no test drives an open circuit through a graph to the desk; the gateway logs 200 characters of a provider's error (an in-region model could echo unscrubbed text); a bad MCP token fails before any audit row, and the "allowed" row is written before a booking that may fail; the worker heartbeat runs on its own thread, so `/health` can say "ok" after the job loops die; a brand after a dose that the model didn't list can still lend its dose, capitalised or not ("Continue amlodipine, 40 mg Telma at night"); "interrupt" isn't in the negation list.
- **#18 was itself merged at 05:09 UTC, before its review was posted**, so only its first commit (the log entries) reached `main`. The reviewed fixes landed through [#19](https://github.com/das0777/sahyog-care-companion/pull/19), unchanged from #18's reviewed head. From here on, the agent confirms the merged head matches the reviewed head before writing any log entry.
- **Round 2 on #18: OK to merge.** The reviewer re-ran its probes: S2's fixes are back, the golden set keeps 21/22, the leaks close when the model lists both medicines, and the docs carry the MVP labels.

### #20 · Architecture pack and review guide

| | |
|---|---|
| **Pull request** | [#20](https://github.com/das0777/sahyog-care-companion/pull/20), the pack ported from the MVP at `dbeb7bb`, with a note that it describes the MVP |
| **Review** | A new independent AI review agent (Claude, fresh), run by the coding agent. Two rounds, on the pull request. It checked every diagram against the graph code. The owner didn't read it line by line |

- **What held:** the node names and edges of all four graphs match the code exactly; spot checks match (23 tables, 4 MCP tools, the breaker at 5 failures for 30 s, the 600 s audio sweep, streaming only after the safety check).
- **Round 1: changes needed, four must-fix items, each a statement a client architect could catch.** It named a tag that exists only in the MVP; MVP numbers read as this build's, including "the second pass closed that gap" when probe 3 wasn't blind and the independent check never ran; the W3 diagram labels described the MVP's looser grounding; and the CMO row claimed diagnosis and dose refusal without saying the word checks are a weak backstop. **Fixed**, with the reviewer's wording, plus three diagram colours and the patient-ID sentence. The PDF was regenerated.
- **Round 2: OK to merge.** The reviewer checked the corrected text in both the markdown and the PDF.
- **Where the agent was wrong:** the pack was carried over with a general "written for the MVP" note, but the note didn't cover specific false statements, as #18's review had already found for the other docs.
- **Recorded, not changed:** the W2 ask diagram has no path for rules that didn't load (the API catches `RulesNotLoaded` and sends it to the desk); lines on ingest fencing and the desk lock could say more.

