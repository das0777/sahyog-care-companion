# ADR 0005: Hybrid deployment with an egress boundary

**Status:** Proposed, for the steering review. Nothing here is deployed · **Date:** 2026-10-30

## Context

Identified data must be stored and processed in India (PRD constraints). The peak is 1,400 requests an hour. This build has only run on one Mac, with one API process.

## Proposal

| Inside the hospital's India boundary | Outside, reached only through the gateway |
|---|---|
| API, worker, Postgres with pgvector, Redis, object store | The large and small models, on scrubbed text only |
| OCR, embeddings, speech to text | |
| Scrubber and its placeholder map | |

- **One way out:** the only outbound path for clinical text is the model gateway, and it scrubs first. Enforce that at the network too, with an egress allowlist naming only the provider's host, because a code-level rule is one bug from failing.
- **In-region model for drafting:** the Ollama adapter is built, but unverified on a real server. Identified drafting should use it, or an India-hosted model.
- **Scale:** run API replicas without shared memory, which the checkpointer already allows. Move the circuit breaker's state to Redis, since it's per process today. Run the worker on separate machines.
- **Queue:** Postgres held at this load in testing here. Revisit it with a load test on the real infrastructure.

## What must be proved before this is real

- A load test on the real infrastructure. The one in S7 measures a Mac, not capacity.
- Restore within 4 hours and 99.5% availability. Neither has been tested, and no backup job exists.
- OIDC instead of the development sign-in, which must stay off in any shared environment.
- A provider contract covering data handling, or an in-region model for all clinical text.
- An independent security review of the threat model, including prompt injection through uploaded reports.
