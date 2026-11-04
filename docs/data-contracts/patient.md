# patient

| | |
|---|---|
| **Owner** | Records service |
| **Sensitivity** | Direct identifiers |
| **Schema version** | 1 (migration 0001) |
| **Notes** | Never leaves the boundary; tokenised before any external call. |

## Checks

- patient_id unique, format P + 4 digits
- abha_id unique, format NN-NNNN-NNNN-NNNN
- phone in +91 55 range while synthetic
- synthetic = true for every seeded row
