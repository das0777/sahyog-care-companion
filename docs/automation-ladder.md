# D1 · Automation ladder

Every task, placed on a rung by four questions: (1) is the rule fully known and stable, (2) is the input bounded and well formed, (3) what does a wrong answer cost and who notices it, (4) who must sign off before the effect is real. Rungs: **1** deterministic code, **2** LLM-augmented (one fuzzy step inside checked code), **3** agentic loop, **4** human decides.

**Written after the build** (2026-11-05), not on day 1 as the pack asks. The "In the build" column is where the code put each task, so it can be checked.

## The pack's twelve client tasks

| Task | 1 Rule known? | 2 Input bounded? | 3 Cost of a wrong answer, and who notices | 4 Who signs off | Rung | In the build |
|---|---|---|---|---|---|---|
| Is the slot still free | Yes | Yes | A double booking, noticed at the clinic | Nobody | 1 | `scheduling/service.py` `reserve_slot`, plus DB triggers |
| Send the confirmation | Yes | Yes | A wrong message, noticed by the patient | Nobody | 1 | SMS outbox rows. `notify.deliver` refuses synthetic patients |
| PDF to text | Yes | Mostly (scans vary) | A misread number, possibly unnoticed | Nobody | 1 | `ingest/parse.py`, with OCR flagged so W2 warns |
| Medicine in stock | Yes | Yes | A wrong flag, noticed by the pharmacy | Nobody | 1 | `scribe/stock.py`, flags only |
| Red flags: rules first, LLM second | Partly (phrasing is open) | No | **A missed emergency: patient harm** | The ER or desk acts | 2, with rules as a floor | `safety/red_flags.py`, then the model second pass. Fails closed |
| Symptoms to a specialty | No | No | A wrong clinic, noticed by the doctor | The desk on low confidence | 2 | W1 `match_specialty`, with one clarifying question, then the desk |
| Answer a question on a report | No | No | A wrong value, possibly unnoticed | Nobody, so code checks citations and numbers | 2 | W2 ask, with `safety_check` in code |
| Dictation to a SOAP note | No | No | **An unsaid drug or dose: patient harm** | The doctor, every time | 2, then 4 | W3 `draft_soap`, `extract_meds`, grounding in code |
| Does this question need a doctor | No | No | Advice given, possibly unnoticed | The desk or doctor | 2 | Word checks (a backstop: 6/25 unseen) plus the model flag |
| Choose among six candidate doctors | Partly | Yes | A slower slot, noticed by the patient | The patient picks | 3 → **built as 1 + 4** | Shortlist in code, and the patient picks at an interrupt. No agentic loop was needed |
| Sign the clinical note | No | — | **Patient harm, legal record** | The doctor | 4 | The W3 `review` interrupt. The API refuses signing with gaps open |
| Pick a substitute medicine | No | — | **Patient harm** | The doctor | 4 | Not automated. Stock is flagged, and the doctor chooses |

## Six tasks found during the build

| Task | 1 | 2 | 3 | 4 | Rung | In the build |
|---|---|---|---|---|---|---|
| Is this uploaded report someone else's | Mostly | No (printed names vary) | **A record under the wrong patient** | The desk reviews held reports | 1, failing to 4 | `ingest/identity.py`. Every name word must match, else held |
| Does an uploaded report hide instructions for the AI | No | No | A data leak, if the filter failed | The desk reviews quarantined chunks | 1 as a first filter | `ingest/scan.py`. The real defence is the SQL filter |
| Remove identifiers before any outside call | Mostly | No | **Identified data leaves India** | Nobody | 1 | `safety/deid.py`, plus the gateway refusing identified system prompts |
| May this family member read this record | Yes | Yes | **A privacy breach** | Nobody | 1 | `records/scope.py` `can_read`, checked on every read |
| Cancel or move a booking for a patient | Yes | Yes | A lost appointment | The desk, with a reason | 4 | Desk override: locked, audited with the reason |
| Is a medicine the doctor said negated nearby | No | No | **An unwanted prescription** | The doctor | 1, failing to 4 | Any negation in the sentence makes it a gap the doctor confirms |
