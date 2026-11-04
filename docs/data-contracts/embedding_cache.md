# embedding_cache

| | |
|---|---|
| **Owner** | Records service |
| **Sensitivity** | Operational |
| **Schema version** | 1 (migration 0003) |
| **Notes** | Vectors by content hash, so a re-uploaded report isn't embedded twice. |

## Checks

- holds no text; keyed on hash and model
