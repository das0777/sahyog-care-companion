# ingest_job

| | |
|---|---|
| **Owner** | Records service |
| **Sensitivity** | Operational, tied to a patient |
| **Schema version** | 1 (migration 0003) |
| **Notes** | One upload's trip through the worker. Postgres is the queue. |

## Checks

- attempts never exceed 3; a job with an expired lease can be claimed by another worker
