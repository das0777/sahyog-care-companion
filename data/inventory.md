# D5 · Data inventory and sizing

## What this build actually uses

**All data is generated.** The pack's five public datasets (the Kaggle no-show, transcription, symptom, Indian medicine and healthcare sets) **were never loaded**. The specialty crosswalk, red-flag rules and medicine list were written by hand in `sahyog/seed/`, and everything else comes from the deterministic seed (`sahyog/seed/generate.py`, `make seed`). Licences of the public sets therefore don't apply to anything in the repo. Counts below are measured on a fresh full seed (`sahyog_eval`, 2026-11-05).

| Source | Rows | Licence | Made by |
|---|---|---|---|
| Specialties, with red-flag rules | 38 | Own | `seed/catalogue.py`, `seed/red_flags.yaml` |
| Clinics, in 4 cities | 12 | Own | Seed |
| Doctors | 500 | Own (Faker en_IN names) | Seed |
| Booking blocks, 14 days | 42,000 | Own | Seed |
| Patients, with Devanagari names | 1,000 | Own (Faker en_IN and hi_IN) | Seed |
| Caregiver consents (some expired) | 50 | Own | Seed |
| Medicine stock rows | 360 | Own | Seed, CSV adapter |
| Synthetic report PDFs (text, scanned, Hindi, mixed, red-team, bad files) | 67 | Own | `make w2-samples` |
| W3 golden dictations | 40 | Own | `evals/w3/golden.jsonl` |

## The pack's three "enough" checks, measured

| Check | Result | Status |
|---|---|---|
| Every specialty has at least ten doctors | 18 of 38 do. **20 have fewer, and the smallest has 2** | **Fails** |
| Every clinic has slots on every working day | All 12 clinics have slots on all 14 seeded days (7 days a week) | Passes |
| Every eval case has at least five candidate chunks | **2 of 84** W2 ask cases do. The sample reports are short: 1 to 5 chunks each | **Fails** |

**What failing means:** the generator spreads 500 doctors over 38 specialties unevenly, and each eval case has one short report. Both make retrieval and matching easier than real data would. Fixing them needs a seed change (at least 10 doctors per specialty) and longer, multi-report patients in the W2 eval set. Neither is done.

## Sizing at Sahyog's scale (the pack's rules, unchanged)

| Store | Rows at scale | Estimate | This build |
|---|---|---|---|
| Vector index | 60,000 chunks from 2,000 PDFs | About 246 MB float32 | Same 1,024-dimension e5-large vectors |
| Slot calendar | 480,000 rows | About 38 MB | 42,000 rows for 14 days |
| Checkpoints | 9,000 runs a day, about 8 steps | Tens of MB a day | Purged by a manual `make purge-threads`. No schedule |
| Audio | 9,000 consultations × 8 minutes | About 70 GB a day, deleted within 24 h | Swept every 10 minutes, plus a 1-day bucket rule |
| Traces | 1 row per model call | Small | No retention job (recorded in #17's review) |
