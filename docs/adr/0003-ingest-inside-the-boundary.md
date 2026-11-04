# ADR 0003: Ingest runs inside the boundary, on a Postgres queue

**Status:** Accepted with S3 · **Date:** 2026-10-30

## Context

Uploaded reports hold identifiers and clinical detail. W2 needs OCR, embeddings and a worker pool. The spec asks for a queue with workers and text stored within 60 seconds.

## Decisions

1. **OCR and embeddings run locally.** Tesseract (English and Hindi) and `intfloat/multilingual-e5-large` (1,024 dimensions, about 2.2 GB). Report text never leaves the boundary at ingest, and the ingest code can't import the model gateway.
2. **Postgres is the queue.** Jobs are claimed with `FOR UPDATE SKIP LOCKED`, so a document and its job commit together and no new service is needed. A lease recovers jobs from dead workers, with 3 attempts at most. This may need revisiting under load in S7.
3. **The worker is a separate service**, so OCR and embedding can't starve triage.
4. **PDFium is used one thread at a time.** It isn't thread-safe: two workers using it at once crashed the process during S3's first eval. OCR runs outside the lock.
5. **A chunk never crosses a page**, so a citation's page is always right.
6. **The patient filter runs first in search,** in a materialised CTE. A filter applied after an approximate vector index can silently return too few results, and one patient has few chunks, so an exact search is fast.
7. **OCR-read chunks are marked**, with a confidence. A misread number can't always be detected, so later stages must be able to say a value came from a scan.

## Consequences

- OCR is weaker than a cloud service on poor scans, and measured quality comes from synthetic scans only.
- Each process that embeds holds about 2–3 GB in memory, and `make reset` deletes the downloaded model.
- A prompt-injection scan by pattern is a first filter only: S4's SQL filter and citation check are the defence.
