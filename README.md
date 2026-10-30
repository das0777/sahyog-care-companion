# Sahyog Care Companion

Agentic patient and doctor workflows for a hospital network: find the right doctor (W1), ask questions over your own records (W2), and draft consultation notes for a doctor to sign (W3).

The project is built in gated stages. See [JOURNAL.md](JOURNAL.md) for where it stands and [docs/stages/](docs/stages/) for each stage's scope and test pack.

## Run it

You need Docker Desktop and `make`.

```bash
make up          # build, start Postgres+pgvector, Redis, MinIO and the API, apply migrations
make seed        # load deterministic synthetic data
make test        # run the test suite against a separate test database
```

The API is at http://localhost:8000 (interactive docs at `/docs`). The MinIO console is at http://localhost:9101.

## Try it

```bash
make token role=patient id=P0001     # prints a dev token
curl -H "Authorization: Bearer <token>" localhost:8000/patients/P0001
```

Roles: `patient`, `caregiver`, `doctor`, `desk`, `pharmacist`, `compliance`. Every read of a patient record is written to the audit log; a compliance token can ask `GET /audit?record_id=P0001`.

## Safety and evals

```bash
make eval                                   # offline safety, W1 and W2 evals; exits non-zero on a gate failure
make eval GUARDRAILS=off                    # same run with the guardrails off: must fail
make redflag text="seene mein dard hai"     # the red-flag gate on one message
make scrub text="..." patient=P0001         # what would leave the hospital boundary
```

## Records (W2 ingest)

```bash
make w2-samples                                       # synthetic report PDFs
make upload file=evals/w2/generated/text-lab-0.pdf patient=P0001
make doc-status job=<job_id> patient=P0001
make search patient=P0001 q="HbA1c"
```

A separate `worker` service reads, indexes and embeds uploads, entirely inside the boundary. The first `make up` downloads a 2.1 GB embedding model, and `make reset` deletes it. Decisions: `docs/adr/0003-ingest-inside-the-boundary.md`.

Reports go to `evals/reports/` (git-ignored). Every model call goes through `sahyog/llm/gateway.py`; vendor SDKs are imported only in `sahyog/llm/adapters/`. To add a real model's key without showing it, run `make set-key`, then try one call with `make llm-smoke`. Rules: `docs/safety/red-flag-rules.md`.

## Make targets

| Target | What it does |
|---|---|
| `make up` / `make down` | Start or stop the stack (data kept) |
| `make reset` | Stop and delete all data volumes |
| `make migrate` | Apply database migrations |
| `make seed` | Replace seed data; the audit log is never cleared |
| `make test` / `make lint` | Tests; lint and format check |
| `make token role=… id=…` | Issue a local dev token |
| `make eval` | Safety evals (`GUARDRAILS=off` to prove they fail without the guardrails) |
| `make redflag text=…` / `make scrub text=… patient=…` | Try the red-flag gate / the scrubber |
| `make llm-smoke` | Optional: one real model call (needs a key) |
| `make psql` | Open psql on the dev database |

## Ports

| Service | Host port |
|---|---|
| API | 8000 |
| Postgres | 5433 |
| Redis | 6380 |
| MinIO API / console | 9100 / 9101 |

## Data

All data is synthetic: 38 specialties, 12 clinics in 4 cities, 500 doctors, 14 days of one-hour booking blocks, 1,000 patients and 50 caregiver consents. Phone numbers use the `+91 55` range, which is not an Indian mobile range, so nobody real can be contacted.

## Layout

```
sahyog/            application package
  api/             routers
  seed/            synthetic data generator
  safety/          red-flag gate, language detection, de-identification
  llm/             model gateway, output schemas, vendor adapters
  evals/           eval runner and the egress replay
  auth.py          dev tokens and the per-request auth context
  audit.py         audit on every patient-scoped read
  models.py        the 14 tables
migrations/        Alembic migrations, including the database safety triggers
evals/             golden cases, malformed-output fixtures, reports (git-ignored)
config/            prices.yaml for the cost meter
tests/             schema, database rules, seed and API tests
docs/              stages, data contracts, ADRs
```
