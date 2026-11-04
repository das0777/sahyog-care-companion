# S0 · Test pack

| | |
|---|---|
| **Stage** | S0 Foundation |
| **Branch** | `stage/s0-foundation` |
| **Handed over** | 2026-10-29 (revised the same day once the full Docker stack ran) |
| **Claude's result** | All checks A1–A10 pass on the full Docker stack: 35 of 35 tests, lint clean |

## What changed since the first hand-over

The first version of this pack could not run A1 and A2, because Docker image pulls hung. Pulls recovered later the same day, and running the full stack turned up two problems, both fixed:

1. **MinIO image removed from Docker Hub and Quay.** MinIO no longer publishes community images, so `minio/minio:RELEASE.2025-04-22T22-12-26Z` cannot be pulled anywhere. The stack now uses `bitnamilegacy/minio:2025.4.22`, Bitnami's frozen build of that same MinIO release, so behaviour (buckets, the 24 h audio expiry rule) is unchanged.
2. **Seed differed by host time zone.** Faker's date-of-birth helper converts through local time, so 84 of 1,000 patients got a date of birth one day apart on the Mac (IST) and in the container (UTC). The date of birth is now drawn from the seeded random generator, and a new test seeds under three time zones and checks the fingerprint is identical. The fingerprint is now `3db173f11c0d0f79` everywhere.

## Claude's results

| # | Check | Result | Evidence |
|---|---|---|---|
| A1 | Stack starts with one command | Pass | `make reset` then `make up`: 4 containers healthy and migration `0001` applied in about 32 s |
| A2 | Health reports each dependency | Pass | `{"status":"ok","postgres":"ok","redis":"ok","minio":"ok"}` |
| A3 | Schema matches the spec | Pass | `test_all_fourteen_spec_tables_exist`, HNSW and GIN indexes, 4 triggers installed |
| A4 | Seed complete and repeatable | Pass | Two runs in the container and one on the Mac: 38 / 12 / 500 / 42,000 / 1,000 / 50 / 360, fingerprint `3db173f11c0d0f79` every time |
| A5 | Roles enforced | Pass | P0001 → P0002: 403; D0001 → P0002: 200; caregiver, pharmacist, compliance: 403 |
| A6 | Every read audited | Pass | `/audit?record_id=P0002` shows the denied patient read, the allowed doctor read, and the compliance query itself |
| A7 | Audit cannot be altered | Pass | `ERROR: audit_event is append-only: UPDATE rejected`; DELETE and TRUNCATE also rejected (tests) |
| A8 | Block cannot be overbooked | Pass | Same `(slot_id, token_no)` rejected; token above capacity rejected; duplicate idempotency key rejected |
| A9 | No secrets committed | Pass | `.env` git-ignored; only local dev defaults in `.env.example` |
| A10 | All tests green, lint clean | Pass | `35 passed in 0.99s`; `All checks passed!` |

Extra checks beyond the stage doc: a failed audit write returns 500 and no data; a signed clinical note cannot be updated or deleted, while a draft can; seeding never clears the audit log; seeded phones are all in the non-mobile `+91 55` range; the `audio` bucket carries the `audio-expiry` rule (1 day); the seed is identical in every host time zone.

## Your test script

Run these from `~/Desktop/sahyog-care-companion`. Each step shows what you should see.

**1. Start the stack (A1)**

```bash
make up
```

Expect: four containers reported `Healthy` (`postgres`, `redis`, `minio`, `api`), then `Running upgrade  -> 0001`. The first run downloads images and builds the API, so it takes a few minutes; later runs take about 30 s.

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

Expect both times: specialty 38, clinic 12, doctor 500, slot 42,000, patient 1,000, consent 50, medicine_stock 360, and fingerprint `3db173f11c0d0f79`.

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

Expect: `ERROR:  audit_event is append-only: UPDATE rejected`.

**7. Overbooking (A8) and the full suite (A10)**

```bash
make test
make lint
```

Expect: `35 passed`, then `All checks passed!`.

**8. Secrets (A9)**

```bash
git check-ignore .env
git grep -nE "sk-ant|ANTHROPIC_API_KEY=.+" -- ':!docs' || echo "no keys"
```

Expect: `.env`, then `no keys`.

**Optional: look around**

- API docs: http://localhost:8000/docs
- MinIO console: http://localhost:9101 (login from `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` in `.env`): buckets `audio` and `reports`.

## Known limitations

- Caregivers are always denied in S0. Consent enforcement comes in S4.
- Doctors and desk can read any patient record. Narrowing doctors to their own patients is a later access-matrix refinement.
- Dev tokens stand in for OIDC and must not be used in any shared environment.
- Blocks are generated every day, including Sundays, so counts are identical whatever day the seed runs.
- `bitnamilegacy/minio` is a frozen image that gets no security updates. That is fine for a local stack; a shared or production setup would use a managed S3-compatible store instead.

## Your verdict

Reply **"S0 accepted"**, or list what failed by step number.
