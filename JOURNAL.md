# Sahyog Care Companion · Project Journal

The single record of how this project is executed: where we are, what was done, what was decided and why, and what comes next. Newest log entry at the bottom. Read **Now** first.

---

## Now

| | |
|---|---|
| **Current stage** | Pre-S0: planning complete, waiting on three decisions |
| **Last thing done** | Stage plan and stage-gate process agreed (2026-10-29) |
| **Next action** | User answers the S0 decisions (below), then Claude writes `docs/stages/S0.md` for approval |
| **Blocked on** | User: repo location, LLM provider and key, Docker availability |
| **Last accepted tag** | none yet |

### Open decisions

| # | Decision | Proposed default | Status |
|---|---|---|---|
| Q1 | Repo location | `~/Desktop/sahyog-care-companion` (this folder), not inside zerowire-v1 | Open |
| Q2 | LLM provider | Anthropic API: Sonnet 5.5 for triage and drafting, Haiku 5.5 for cheap steps; local Ollama as the in-region fallback; a fake model for all tests. The user adds the key to `.env` themself | Open |
| Q3 | Docker | Docker Desktop installed and running on the Mac | Open |

---

## Stage board

| Stage | Name | Status | Branch | Tag | Test pack |
|---|---|---|---|---|---|
| S0 | Foundation | Planned | `stage/s0-foundation` | | |
| S1 | Safety core + eval harness | Planned | `stage/s1-safety` | | |
| S2 | W1 Find my doctor | Planned | `stage/s2-w1` | | |
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
