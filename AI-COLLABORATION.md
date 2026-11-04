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
