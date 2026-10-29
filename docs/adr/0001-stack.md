# ADR 0001 · Platform stack

| | |
|---|---|
| **Status** | Accepted for S0 |
| **Date** | 2026-10-29 |

## Context

The engagement pack fixes the main components: LangGraph for the agent graphs, FastAPI, Postgres with pgvector, an object store, Presidio, Langfuse, ragas and faster-whisper. Identified data must stay in India, and the stack must start with one command for the demo and the reviewers.

## Decision

- **Python 3.12** with `uv` for dependencies and a lock file.
- **FastAPI** for the API, with one router per workflow so W1, W2 and W3 can scale apart later.
- **Postgres 16 + pgvector 0.8** as the only database. It holds relational data, vectors (HNSW), full-text (`tsvector`) and, from S2, the LangGraph checkpoints.
- **SQLAlchemy 2 + Alembic** for models and migrations. Safety rules (append-only audit, immutable signed notes, block capacity) are database triggers, so they hold even if application code is wrong.
- **Redis 7** for the short-lived availability cache (30 s).
- **MinIO** as an S3-compatible object store, with a 24 h expiry rule on the audio bucket.
- **Docker Compose** for the whole local stack.
- **Local HS256 dev tokens** in place of OIDC, because auth is kept as in the reference architecture.

Python 3.12, Postgres 16 and MinIO were Claude's choices; the pack does not name versions.

## Consequences

- One database is simpler to run and back up. If retrieval load grows, the ADR on deployment (D6) says when vectors move out.
- Triggers move some rules out of Python, so they are covered by database tests (`tests/test_db_rules.py`).
- Dev tokens must be replaced before any shared environment. The secret in `.env.example` is local-only.
