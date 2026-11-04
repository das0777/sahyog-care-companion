# Sahyog Care Companion · Final report and combined test pack

| | |
|---|---|
| **Status** | All eight stages built and accepted by the user on 2026-10-30, on `main`. **Accepted as matching the brief, not as ready for patients** |
| **Branch** | `main`, tags `s0-accepted` to `s7-accepted` |
| **Date** | 2026-10-30 |
| **Evidence** | 334 tests and lint green; all offline gates pass on a clean rebuild; 17 checks fail with guardrails off, as they should |

## The verdict

**It works end to end as a demo on synthetic data. It isn't safe for real patients.** The numbers below are mostly excellent, and most of them are weak evidence, because Claude wrote the code, the prompts and nearly all the test cases, and a Claude model answered them. Where someone other than Claude could have tested it, nobody yet has.

## See it working

Open **http://localhost:8000/** and follow [the demo script](demo-script.md). Each role has a sign-in on the first screen. To reset the data, run `make seed`.

## Scoreboard against the PRD

| Goal | Metric | Target | Result | Trust |
|---|---|---|---|---|
| G1 | Specialty accuracy | ≥ 85% | 38/38 | Low: same author; 18 accept either of two specialties |
| G1 | Red-flag recall | 100%, no exceptions | Known cases 100%. Probe 3: rules alone 7/15, with the model 15/15 | **Low, and the most important gap. See risk 1** |
| G1 | Median time to book | < 3 min | **Not measured**: needs real people | |
| G1 | Bookings without a call | ≥ 70% | **Not measured**: needs real people | |
| G2 | Answer faithfulness, calibrated | ≥ 0.9 | 0.99, **uncalibrated** | Low: a model grading a model |
| G2 | Scope leaks, red-team set | 0 | 0 in 26, plus 0 in 90 searches | **High for data access**, because the filter is in SQL |
| G3 | Doctor review time | ≤ 90 s | **Not measured**: needs real doctors | |
| G3 | Invented molecules | 0 | 0 in 37 dictations | Medium: code enforces it, but the real model never tried, so the check has fired only on a scripted model |
| G4 | Record reads audited | 100% | Every read path has a test | Medium: no independent audit of completeness |
| G5 | Identified data leaving India | 0 | 0 of the patient's identifiers in replay. **Other people's names can leak: see risk 3** | Medium |
| NFR | Triage turn, p95 | < 4 s | 3.3–4.3 s: **narrow miss** at the target rate, pass at three times the rate. Too few runs to separate them | Medium |
| NFR | Record answer, p95 | < 8 s | 7.1–7.8 s under load | Medium |
| NFR | Note draft, p95 | < 20 s | 7.0 s | Medium: one at a time |
| NFR | PDF stored, with status | < 60 s | 2–10 s | Medium: a killed job takes 3 minutes |
| NFR | Load, 1,400 requests an hour | Load-tested | 143 requests in 5 min, 2 sent to the desk (503). 181 in 2 min at 3× the rate, 0 errors | **A Mac with one API process, not capacity** |
| NFR | Audio deleted within 24 h | Yes | Tested with a stub. The rule is set | Medium: no real day has passed |
| NFR | Cost per consultation | Formula from traces | $0.017 of model cost for one triage, one answer and one note. **Infrastructure is unpriced** | Medium |
| E6.4 | Second provider passes the eval set | Yes | Gemini 2.5 Flash passed all three **dev** sets with no code change | Medium: dev sets only |
| NFR | Restore < 4 h, availability 99.5% | | **Not tested**, and no backups exist | |

## Biggest risks, in order

1. **Missed emergencies.** Rules alone catch about half of unseen phrasing (8/15, 5/15, 7/15). The model catches the rest of what Claude thought to write. But probe 3 wasn't truly blind, because the prompt echoes its wording, and **the independent check you skipped in S2 has still never run.** This is the first thing to fix.
2. **Speech to text can reverse a meaning.** On a synthetic voice, "Known diabetic" became "NON diabetic", and Hindi was poor. Grounding can't catch it, because it trusts the transcript. The review screen opens with the transcript and a warning, but nothing forces a doctor to read it. Real voices are untested.
3. **Privacy leaks.**
   - Some other people's names reach the outside model: on 12 hard sentences, 10 leaked.
   - OpenRouter is an added third party, and India-only processing isn't provided by this route.
   - The no-collection setting is requested, but not verified.
4. **Scanned numbers can be wrong and look right.** About 1 in 200 on clean scans: creatinine 1.72 was read as 172. Patients see a warning, but real scans are untested and will be worse.
5. **The scrubber relies on a word list.** It twice hid clinical words from the model, first symptoms and then lab test names. Fixed for what was tested, but unseen report words can still be hidden, which causes a wrong "not found" rather than a leak.
6. **Nothing has been clinically reviewed:** red-flag rules, prompts, emergency messages (112, 108, Tele-MANAS 14416), and whether showing a printed reference range is acceptable.

## Your call: decisions I made without you

| Decision | What I did | Why it might be wrong |
|---|---|---|
| Traces | Postgres table, **not Langfuse** as the spec says (ADR 0004) | Langfuse was too heavy for this machine, but it's what the pack names |
| Faithfulness | Published method through the gateway, not the ragas package | Ragas would bypass the scrubber, but the pack names it |
| Screens | One plain web app, no framework | Quick and thin, but a real product would need a design system |
| Hand-offs | To the desk queue, with no separate doctor queue | The PRD says "hand to a doctor" |
| Additions beyond the spec | Wrong-patient hold, number check, scan warning, emergency check on record questions, self-harm message, circuit breaker | You may want them reviewed |
| Second-pass model | The cheaper Haiku, since it matched Sonnet on the spent probes | Equal on 30 cases doesn't prove equal on real ones |

## Only people can do these

| Who | What | How |
|---|---|---|
| **You, or preferably a clinician** | Write 20+ emergency and 10+ non-emergency phrasings. **The most valuable item here** | Paste into `evals/w1/heldout/emergency.txt` and `not_emergency.txt`, then `make eval-live set=heldout` |
| A clinician | Review the rules, prompts and messages | `sahyog/seed/red_flags.yaml`, `sahyog/graphs/*_prompts.py`, `*_messages.py` |
| Someone at Sahyog | Provide anonymised real scans and dictated audio | Measure with the existing evals |
| A person | Grade 20 answers to calibrate the judge. 5 are ready, and 15 more are needed | `evals/w2/judge_sample.jsonl`, then `make eval-live set=ask-calibrate` |
| A privacy reviewer | OpenRouter, DPDP, and names reaching it | ADR 0004, ADR 0005 |
| Real doctors and patients | Time to book, review time, calls avoided | Needs a pilot |
| The infrastructure team | Real load test, backups, restore, OIDC | ADR 0005 |

## Please check these on your Mac

- **This project is in iCloud Drive** (the Desktop folder), including `.env` with your OpenRouter key. iCloud caused a failed git commit, the slowness and, most likely, the stray `name 2` files, so **I recommend moving the project out of iCloud.** I didn't, because it's your folder.
- **Revoke the OpenRouter key pasted in chat**, if the one in `.env` isn't a new one. If you reused it, replace it, because it's in this conversation's transcript.
- **Stray `name 2` files:** still there, ignored by git and tests.

## What's not built

- Note amendment: a signed note can't be changed, and no new version can be made yet.
- A screen for moving a booking (the API does it), late-block scheduling (it runs when the queue is read), and speaker separation.
- A doctor queue, a real SMS gateway, a hospital FHIR link, and the semantic cache.
- Traces for graph nodes and tools: only model calls are traced.
- Backups, audit retention at 1 year, and deletion of a patient's data on request.
- Marathi, and any screen in Hindi: the screens are in English, though patient messages from the assistant follow the patient's language.
- Live wait-time estimates, a Pro extension.

The microphone button and a successful upload through the file picker weren't clicked. Both underlying API paths were tested.

## Stage by stage

| Stage | Test pack | One-line result |
|---|---|---|
| S0–S3 | [S0](stages/S0-test-pack.md), [S1](stages/S1-test-pack.md), [S2](stages/S2-test-pack.md), [S3](stages/S3-test-pack.md) | Accepted, tagged, on `main` |
| S4 Ask (accepted) | [S4](stages/S4-test-pack.md) | Right answers 23/23 and 5/5 extended; no other patient's data |
| S5 Scribe (accepted) | [S5](stages/S5-test-pack.md) | First measured run: precision 93%, gap 4/5, fixed after. Extended 22 dictations: 100% and 9/9 |
| S6 Screens (accepted) | [S6](stages/S6.md) | All roles clicked through in a browser |
| S7 Assurance (accepted) | [S7](stages/S7.md) | Breaker, traces, cost, MCP server, load test, more cases, this report |

**Real model spend for the whole build:** about $4–5 on OpenRouter, added up from each run's printed cost, not from a bill.

## Review

The user replied "All accepted" on 2026-10-30. No results from the user's own testing were reported. Accepting means the build matches what was asked. It doesn't mean it's ready for patients: the list under "Only people can do these" remains open.
