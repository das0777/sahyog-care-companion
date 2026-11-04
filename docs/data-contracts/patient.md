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
- phone in +91 55 range while synthetic. That's outside India's mobile ranges (6 to 9), but it can match a real landline, so **no SMS or call adapter may contact a patient with synthetic = true**
- synthetic = true for every seeded row
