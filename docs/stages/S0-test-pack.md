# S0 · Test pack

| | |
|---|---|
| **Stage** | S0 Foundation |
| **Branch** | `stage/s0-foundation` |
| **Handed over** | 2026-10-29 |
| **Claude's result** | 33 of 34 tests pass, lint clean. A1, A2 and the health test still need the full Docker stack (see "Blocker") |

## Blocker found during the build

Docker Desktop on this Mac could not download images. Every `docker pull`, even `hello-world`, hung without progress, while the Mac itself reached Docker Hub fine and running containers had internet. The pinned images in `docker-compose.yml` (`pgvector/pgvector:0.8.0-pg16`, `redis:7.4-alpine`, `minio/minio:RELEASE.2025-04-22T22-12-26Z`, `python:3.12-slim`) could not be fetched.

To keep going, Claude ran Postgres from an image built locally (`sahyog-local/postgres-pgvector:16-0.8.0`, from your cached `postgres:16-alpine` with pgvector 0.8.0 compiled in) and Redis from your cached `redis:7-alpine`, and ran the API and tests on the Mac with `uv`. MinIO could not be run that way. The compose file itself is unchanged and still uses the official images.

**Your step before testing:** restart Docker Desktop, then check that `docker pull hello-world` finishes. If it still hangs, look at Docker Desktop → Settings → Resources → Proxies.

## Claude's results

| # | Check | Result | Evidence |
|---|---|---|---|
| A1 | Stack starts with one command | **Not run** | Blocked by image pulls |
| A2 | Health reports each dependency | **Partly** | Postgres and Redis report `ok`; MinIO not running, so `/health` returns 503 as designed |
| A3 | Schema matches the spec | Pass | `test_all_fourteen_spec_tables_exist`, HNSW and GIN indexes, 4 triggers installed |
| A4 | Seed complete and repeatable | Pass | Two full runs: 38 / 12 / 500 / 42,000 / 1,000 / 50 / 360, fingerprint `2824c0f543177b7e` both times, about 2 s each |
| A5 | Roles enforced | Pass | P0001 → P0002: 403; D0001 → P0002: 200; caregiver, pharmacist, compliance: 403 |
| A6 | Every read audited | Pass | `/audit?record_id=P0002` shows the denied patient read, the allowed doctor read, and the compliance query itself |
| A7 | Audit cannot be altered | Pass | UPDATE, DELETE and TRUNCATE on `audit_event` rejected by trigger |
| A8 | Block cannot be overbooked | Pass | Same `(slot_id, token_no)` rejected; token above capacity rejected; duplicate idempotency key rejected |
| A9 | No secrets committed | Pass | `.env` git-ignored; only local dev defaults in `.env.example` |
| A10 | All tests green, lint clean | **33 / 34** | Only `test_health_reports_each_dependency` fails, because MinIO is missing |

Extra checks beyond the stage doc: a failed audit write returns 500 and no data; a signed clinical note cannot be updated or deleted, while a draft can; seeding never clears the audit log; seeded phones are all in the non-mobile `+91 55` range.

## Your test script

Run these from `~/Desktop/sahyog-care-companion` after Docker pulls work. Each step shows what you should see.

**1. Start the stack (A1)**

```bash
make up
```

Expect: four containers reported healthy (`postgres`, `redis`, `minio`, `api`), then `Running upgrade -> 0001`.

**2. Health (A2)**

```bash
curl -s localhost:8000/health
```

Expect: `{"status":"ok","postgres":"ok","redis":"ok","minio":"ok"}`

**3. Seed twice (A4)**

```bash
make seed
make seed
```

Expect both times: specialty 38, clinic 12, doctor 500, slot 42,000, patient 1,000, consent 50, medicine_stock 360, and the same fingerprint (`2824c0f543177b7e`).

**4. Roles (A5)**

```bash
P1=$(make -s token role=patient id=P0001)
DR=$(make -s token role=doctor id=D0001)
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $P1" localhost:8000/patients/P0002
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $DR" localhost:8000/patients/P0002
```

Expect: `403`, then `200`.

**5. Who saw the record (A6)**

```bash
CO=$(make -s token role=compliance id=COMP01)
curl -s -H "Authorization: Bearer $CO" "localhost:8000/audit?record_id=P0002" | python3 -m json.tool
```

Expect three rows in order: P0001 patient `denied`, D0001 doctor `allowed` (purpose `treatment`), and COMP01 compliance `allowed` on `audit_event` (the query itself is logged).

**6. Audit cannot be changed (A7)**

```bash
docker compose exec postgres psql -U sahyog -d sahyog -c "UPDATE audit_event SET actor_id='X'"
```

Expect: `ERROR: audit_event is append-only: UPDATE rejected`.

**7. Overbooking (A8) and the full suite (A10)**

```bash
make test
make lint
```

Expect: `34 passed`, and `All checks passed!`.

**8. Secrets (A9)**

```bash
git status --ignored --short | grep .env
git grep -nE "sk-ant|ANTHROPIC_API_KEY=.+" || echo "no keys"
```

Expect: `!! .env` (ignored) and `no keys`.

## Known limitations

- Caregivers are always denied in S0. Consent enforcement comes in S4.
- Doctors and desk can read any patient record. Narrowing doctors to their own patients is a later access-matrix refinement.
- Dev tokens stand in for OIDC and must not be used in any shared environment.
- Blocks are generated every day, including Sundays, so counts are identical whatever day the seed runs.
- The test suite takes about 100 s when MinIO is unreachable (the client retries). With MinIO up it should be much faster.

## Your verdict

Reply **"S0 accepted"**, or list what failed by step number.
