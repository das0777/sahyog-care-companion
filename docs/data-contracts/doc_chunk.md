# doc_chunk

| | |
|---|---|
| **Owner** | Records service |
| **Sensitivity** | Clinical |
| **Schema version** | 1 (migration 0001) |
| **Notes** | patient_id is copied from the document so retrieval filters in SQL (E4.2). |

## Checks

- patient_id equals its document's patient_id
- embedding has 1,024 dimensions once indexed
- page >= 1
