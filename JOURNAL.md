# Sahyog Care Companion · Project Journal

The single record of how this project is executed: where we are, what was done, what was decided and why, and what comes next. Newest log entry at the bottom. Read **Now** first.

---

## Now

| | |
|---|---|
| **Current stage** | S2 W1 Find my doctor: stage doc in review |
| **Last thing done** | S1 accepted, merged and tagged; S2 stage doc written (2026-10-30) |
| **Next action** | User reviews and approves `docs/stages/S2.md`; then Claude builds S2 |
| **Blocked on** | User: S2 stage doc approval. S2 also needs the user's API key in `.env` and a held-out set not written by Claude |
| **Last accepted tag** | `s1-accepted` (2026-10-30) |

### Open decisions

| # | Decision | Proposed default | Status |
|---|---|---|---|
| Q1 | Repo location | `~/Desktop/sahyog-care-companion` (this folder), not inside zerowire-v1 | **Decided** 2026-10-29 |
| Q2 | LLM provider | Anthropic API: Sonnet 5.5 for triage and drafting, Haiku 5.5 for cheap steps; local Ollama as the in-region fallback; a fake model for all tests. The user adds the key to `.env` themself (needed from S2; S0 and S1 run on the fake model) | **Decided** 2026-10-29 |
| Q3 | Docker | Docker Desktop installed and running on the Mac | **Confirmed** 2026-10-29: Docker 29.5.3, Compose 5.1.4 |

---

## Stage board

| Stage | Name | Status | Branch | Tag | Test pack |
|---|---|---|---|---|---|
| S0 | Foundation | **Accepted** 2026-10-30 | `stage/s0-foundation` | `s0-accepted` | [S0-test-pack.md](docs/stages/S0-test-pack.md) |
| S1 | Safety core + eval harness | **Accepted** 2026-10-30 | `stage/s1-safety` | `s1-accepted` | [S1-test-pack.md](docs/stages/S1-test-pack.md) |
| S2 | W1 Find my doctor | Stage doc in review | `stage/s2-w1` | | |
| S3 | W2 Ingest | Planned | `stage/s3-w2-ingest` | | |
| S4 | W2 Ask | Planned | `stage/s4-w2-ask` | | |
| S5 | W3 Scribe | Planned | `stage/s5-w3` | | |
| S6 | Thin UI | Planned | `stage/s6-ui` | | |
| S7 | Assurance | Planned | `stage/s7-assurance` | | |

Status values: Planned → Stage doc in review → Building → In user testing → Fixing → **Accepted**.

### What each stage delivers and how it is tested

| Stage | Builds | Gate (what the user verifies) |
|---|---|---|
| S0 | Repo, Docker Compose (Postgres + pgvector, Redis, MinIO), FastAPI skeleton, migrations, synthetic seed data, role tokens, audit table | `make up`, `make seed`, `make test` pass; `/health` responds; every API call writes an audit row |
| S1 | Red-flag rule engine, Presidio de-identification and egress scrubber, LLM client with a fake model, 30 golden cases, `make eval` | Red-flag recall 100%; zero identifiers in a 200-payload replay; eval report prints, all before any graph exists |
| S2 | W1 LangGraph: rules → specialty → one clarifying question → hand-off; block booking with tokens; idempotent booking; SMS stub; desk queue and override (E1, E2) | Scripted chats for red flag, vague symptoms, Hinglish and booking; specialty accuracy ≥ 85%; no double booking under concurrency; low-confidence case lands in the desk queue |
| S3 | Upload, OCR, chunking, embeddings, pgvector, visible status (E3.1) | Text and scanned PDF stored and searchable within 60 s with status |
| S4 | Retrieval with the SQL patient filter, citations, foreign-ID check, scope guard, caregiver consent (E3.2, E4) | Answers cite doc and page; faithfulness ≥ 0.9; red-team PDF leaks nothing; expired consent returns nothing; diagnosis and dose refused |
| S5 | faster-whisper, SOAP draft, transcript-grounding check on medicines, stock CSV, doctor-signature interrupt, immutable notes (E5) | Dictate, review and sign; invented medicine blocked; out-of-stock flagged; editing a signed note rejected |
| S6 | Patient web app, doctor console, desk queue screen | All three workflows clicked through in a browser |
| S7 | 80 eval cases with calibrated judge, Langfuse traces, cost meter, load test at 1,400 req/h, ADRs, demo script | Every PRD metric measured in one report; load test meets the p95s |

Tier mapping: S0–S4 = Core, + S5 and S7 = Pro, + load test and MCP server in S7 = Architect.

---

## How we work (the stage gate)

1. **One branch per stage**, never on `main`.
2. **Stage doc first.** `docs/stages/SN.md` holds scope, an acceptance checklist tied to PRD story IDs, and what is out. The user approves it before any code.
3. **Claude tests first.** Unit tests, evals and every earlier stage's tests must be green before handover.
4. **Test pack at handover:** a short report with measured numbers against targets, a copy-paste manual test script with the expected result per step, and known limitations.
5. **User verdict:** "SN accepted", or a list of failures. Failures are logged in the stage doc, fixed, and a new test pack is issued.
6. **Lock:** on acceptance, merge to `main`, tag `sN-accepted`, then open the next stage. Earlier tests stay in the regression suite.
7. **Journal:** this file is updated at every status change. Claude does not start stage N+1 until the user writes "accepted".

### Journal rules

- Update **Now** and the **Stage board** whenever a status changes.
- Add a **Log** entry for each working session: date, what happened, decisions, and what is next.
- Record decisions with their reason in the **Decision log**, so later readers see *why*, not only *what*.
- Never rewrite old log entries. Correct them with a new entry.

---

## Reference documents

| Document | Where |
|---|---|
| Engagement pack (source of truth for the brief) | `~/Downloads/24_Sahyog Care Companion Engagement.pptx.pdf` |
| Architecture canvas (interactive) | https://claude.ai/artifact/WYRJi9NS39F8ZhBuhyrTyZ |
| PRD (live doc) | https://claude.ai/artifact/RoEwGRg2V2n5f3gKJ4GicF |
| Technical specification (live doc) | https://claude.ai/artifact/BNYbjpGL7iGzhMba6btejv |
| PRD PDF export | `~/Downloads/Sahyog Care Companion - PRD.pdf` |
| Spec PDF export | `~/Downloads/Sahyog Care Companion - Technical Specification.pdf` |

The live docs are the current versions. The PDFs are snapshots and must be re-exported after edits.

---

## Decision log

| Date | Decision | Why |
|---|---|---|
| 2026-10-27 | Architecture focuses on the AI layer; auth, gateway and rate limiting kept as in the reference pack | User direction: the AI solution is what is being evaluated |
| 2026-10-27 | Red-flag rules run before any model call, deterministically | Zero tolerance for a missed emergency; rules are auditable and give 100% recall on known phrases |
| 2026-10-27 | Only de-identified text leaves the hospital boundary | DPDP Act and data-residency constraint in the pack |
| 2026-10-28 | Stack: LangGraph, FastAPI, Postgres + pgvector, Redis, MinIO, Presidio, Langfuse, ragas, faster-whisper | Matches the pack; Python 3.12, Postgres 16 and MinIO were Claude's choices, not the pack's |
| 2026-10-28 | Front desk stays in Core (E2.2 and E2.5), not deferred | The pack says the front desk fears replacement and is owed an escalation flow with a queue view; desk override is also the double-booking fix |
| 2026-10-28 | Slots become **blocks with capacity plus a token number** (E2.4) | Nobody can predict how long one consultation takes; a block absorbs a long visit instead of shifting every later booking. Replaces the "one slot = one appointment" assumption |
| 2026-10-28 | Live wait-time estimate is a Pro extension, shown as a range | Needs real per-doctor consultation durations first (from W3 timestamps or a "next patient" tap) |
| 2026-10-29 | Build in eight gated stages (S0–S7) with user sign-off per stage | User wants to test each stage before moving on |
| 2026-10-29 | Evals and guardrails (S1) come before any graph code (S2) | The PRD's release plan rule: evals exist before graphs |
| 2026-10-29 | Defaults adopted: repo here, Anthropic API with a fake model for tests and Ollama as fallback, local Docker | User: "Use defaults" |
| 2026-10-29 | Local ports: API 8000, Postgres 5433, Redis 6380, MinIO 9100/9101 | zerowire's containers already hold 9000 and 6379 on this Mac |
| 2026-10-29 | Safety rules live in database triggers: append-only audit (including TRUNCATE), immutable signed notes, token within block capacity | They must hold even if application code is wrong |
| 2026-10-29 | Audit row is committed in its own transaction before data is returned; denied attempts are logged; a failed audit write fails the request | "Never read without logging" (E6.1) |
| 2026-10-29 | Caregivers denied in S0 rather than allowed without a consent check | Consent enforcement belongs to S4; failing closed is safer |
| 2026-10-29 | Seed phones use the +91 55 range | Not an Indian mobile range, so no real person can ever be texted |
| 2026-10-29 | MinIO runs from `bitnamilegacy/minio:2025.4.22` | MinIO stopped publishing community images; this is the same release, frozen. Fine locally; a shared environment uses a managed S3-compatible store |
| 2026-10-29 | Seed values never come from Faker date helpers | They convert through local time, so data shifted with the host time zone |
| 2026-10-30 | Golden cases and probes are committed before the rules they test | So the git history shows which came first; the only honest way to measure rules written by the same author |
| 2026-10-30 | Red-flag rules are a floor; S2 adds the model second pass and measures it on a held-out set by another author | Blind probes caught 8/15 and 5/15 on unseen phrasing, against 100% on Claude's own cases |
| 2026-10-30 | Scrubber layers: known identifiers, Indian patterns, name gazetteer, structural name rules, then NER | spaCy's small English model misses most Indian names and mislabels Hinglish; no single layer was enough |
| 2026-10-30 | Gateway: reject never repair; retry once; fallback; in-region calls never leave the boundary | Spec rules, enforced in code and tests rather than prompts |
| 2026-10-30 | Anthropic SDK 2.x (API version 2026-10-21); server-side refusal fallback on Sonnet 5.5; SDK retries off | Current SDK; the gateway owns retries so attempts are visible and counted |
| 2026-10-30 | Proposed for S2: a failed second pass goes to the desk, and held-out recall is reported once, never restated after fixes (pending approval of the stage doc) | The gate must never pass by default; S1 showed that post-fix numbers say little about unseen phrasing |

---

## Log

### 2026-10-27 · Understanding the brief
- Read the engagement pack (Sahyog Care Companion, an agentic healthcare build for a hospital network: 9,000 appointments a day, 1,400 requests an hour at peak).
- PDF tools were missing on the Mac, so the text and page images were extracted with a Swift PDFKit script.
- Built an interactive architecture canvas following the user's example image: nodes coloured by automation-ladder rung, stage tags S0–S7, a W1/W2/W3 filter with animated flows. Published as an artifact.
- Fixed a broken character set and a stray hidden panel in the canvas after a local preview.
- Explained D1 (automation ladder), D2 (ten discovery questions) and D3 (assumptions register).

### 2026-10-28 · PRD and specification
- Wrote the PRD: overview, goals and metrics, five personas, scope, epics E1–E6 with testable stories, NFRs, constraints, assumptions, release plan with a timeline, risks.
- Wrote the technical specification: container diagram, agent service, a graph diagram for each of W1, W2 and W3, tools and MCP, data model, API, guardrails, memory, security and threat model, deployment, evals, repo layout and test plan.
- Exported both as A4 PDFs to Downloads.
- User asked whether the front desk was deferred. Checked both docs: it was not, but the Core tier didn't name the desk queue. Made it explicit.
- User raised that consultation length is unpredictable. Designed block booking with tokens, a front-desk queue ordered by red flag then age, late-block tickets, and live wait estimates as a later range-based extension.
- Added a plain-language "How the three workflows work" section to the PRD, stories E2.4 and E2.5, and the Core-tier and gate changes. Updated the spec's Slot and Appointment models, booking response and desk queue API. Re-exported both PDFs.
- Still open: the assumption owners in the register are unassigned and need real people from Sahyog.

### 2026-10-29 · Execution plan
- Split the build into eight stages (S0–S7), each ending in something the user can run and test.
- Agreed the stage-gate process: stage doc → build → Claude's own tests → test pack → user verdict → merge and tag.
- Created this journal.
- **Next:** user answers Q1–Q3, then Claude writes the S0 stage doc for approval.

### 2026-10-29 · S0 stage doc
- User chose the defaults for Q1–Q3. Confirmed tooling on the Mac: Docker 29.5.3, Compose 5.1.4, Python 3.12, uv 0.11.7.
- Initialised the git repo: `main` holds the journal, and work moved to branch `stage/s0-foundation`.
- Wrote `docs/stages/S0.md`: scope (Compose stack, 14 tables, deterministic synthetic seed, dev tokens, audit on every read), what is out, acceptance checks A1–A10, and stage decisions.
- Found port clashes with the zerowire containers (9000, 6379), so offset the MinIO and Redis ports.
- **Next:** user reviews and approves the S0 stage doc; then Claude builds S0 and returns a test pack.

### 2026-10-29 · S0 built
- User approved the S0 stage doc.
- Built:
  - the Compose stack and Makefile;
  - all 14 tables in migration `0001`, with triggers for an append-only audit log, immutable signed notes and token-within-capacity;
  - a deterministic seed (38 / 12 / 500 / 42,000 / 1,000 / 50 / 360 in about 2 s);
  - dev tokens with a per-request auth context;
  - audit on every patient read, including denials;
  - `/health`, `/me`, `/patients/{id}`, `/doctors` and `/audit`;
  - README, 14 data contracts and ADR 0001.
- **Blocker:** Docker Desktop image pulls hang on this Mac, though the Mac and running containers can reach the internet. Worked around it for testing only, with a locally built pgvector Postgres image and cached Redis, running the API and tests on the Mac with `uv`. The compose file still uses the official pinned images.
- Results: 33/34 tests pass and lint is clean. The only failure is the health test, because MinIO could not run. A1 and A2 are not yet verified on the real stack.
- Fixed while building:
  - `alembic` could not import the package (fixed with `prepend_sys_path`);
  - the dev JWT secret was too short;
  - a test used a `:1` literal that SQLAlchemy read as a bind parameter.
- **Next:** user restarts Docker Desktop, runs the S0 test pack, and gives a verdict.

### 2026-10-29 · S0 verified on the full stack
- Docker pulls recovered on their own; the pgvector, Redis and Python images downloaded.
- **Found:** `minio/minio` no longer exists on Docker Hub, and Quay refuses the pinned tag. MinIO has stopped publishing community images. Switched to `bitnamilegacy/minio:2025.4.22` (same release), with data at `/bitnami/minio/data` and a `curl` health check.
- **Found:** the seed fingerprint differed between the Mac (`2824c0f543177b7e`) and the container. Traced it to Faker's `date_between`, which goes through local time: 84 of 1,000 dates of birth were a day apart between IST and UTC. Dates of birth now come from the seeded `rng`, and a new test seeds under three time zones. The fingerprint is now `3db173f11c0d0f79` on both.
- Also fixed: the test pack's secrets check matched its own text; Alembic's `path_separator` deprecation warning.
- Results on the real stack after `make reset` and `make up`: A1–A10 all pass, 35/35 tests in about 1 s, lint clean, `audio` bucket carries the 1-day expiry rule.
- Removed the temporary `sahyog-local/postgres-pgvector` image built during the Docker outage.
- **Next:** user runs the revised S0 test pack and gives a verdict.

### 2026-10-30 · S0 accepted, S1 stage doc
- User ran the S0 test pack and replied "S0 accepted".
- Merged `stage/s0-foundation` into `main` (merge commit, history kept) and tagged `s0-accepted`.
- Wrote `docs/stages/S1.md` on branch `stage/s1-safety`: red-flag engine, language detection, de-identification and egress scrubber, model gateway with a fake model, 30 golden W1 cases, the egress replay and `make eval`.
- **Next:** user reviews and approves the S1 stage doc; then Claude builds S1.

### 2026-10-30 · S1 built
- User approved the S1 stage doc ("Approve S1").
- Committed the 30 golden W1 cases before writing any rule (`bd59208`).
- Built:
  - the red-flag engine (concepts, typo tolerance, combinations, fail-safe negation), with rules in `sahyog/seed/red_flags.yaml` seeded into `Specialty.red_flag_rules`;
  - language detection;
  - the layered egress scrubber;
  - the model gateway with fake, Anthropic (SDK 2.3) and Ollama adapters and a cost meter;
  - `make eval` with the egress replay and an independent detector;
  - `make redflag`, `make scrub` and `make llm-smoke`;
  - ADR 0002 and the red-flag rules guide.
- **Key finding:** two blind probes of 15 unseen emergency phrasings caught 8/15, then 5/15 (probe 2 held out until measured), against 100% on the golden set. Fixed the misses with general rules; both probes are now regression cases. Recorded as the main risk for S2.
- **Method slip, caught:** fixing probe 1 first included phrases echoing probe 2. They were removed before probe 2 was measured.
- Fixed during the build: the "karna/marna" typo misfire; Presidio flagging test dates; spaCy tagging Hinglish and doses as names; North-East and South Indian names leaking; a name rule eating "HbA1c"; the replay planting no out-of-list names; a stale lint config in the image.
- Results: every gate passes; `GUARDRAILS=off` fails (B1 0/13, B5 875 leaks); 161 tests; lint clean.
- **Next:** user runs the S1 test pack, especially step 3 (their own red-flag phrasings), and gives a verdict.

### 2026-10-30 · S1 accepted, S2 stage doc
- User replied "S1 accepted" and listed no failures. No results from the test pack's step 3 (the user's own red-flag phrasings) were reported, so S1 has no recall number from another author.
- Merged `stage/s1-safety` into `main` (merge commit, history kept) and tagged `s1-accepted`.
- Wrote `docs/stages/S2.md` on branch `stage/s2-w1`: the W1 graph, model second pass, specialty match with one clarifying question, block booking, SMS stub, desk queue and override, and a measuring order that freezes prompts before held-out recall is run.
- **Found while planning:**
  - S0's token rule stops a cancelled place from ever being rebooked; the fix is planned in migration `0002`.
  - The golden set has only 17 non-emergency cases (2 Hinglish, 1 Hindi), too few for the accuracy gates; about 50 cases are added before the graph.
- S2 is the first stage that needs a real model: the user adds an API key to `.env` themself, and supplies a held-out set not written by Claude.
- **Next:** user reviews and approves the S2 stage doc; then Claude builds S2.
