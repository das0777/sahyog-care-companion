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
