# medicine_stock

| | |
|---|---|
| **Owner** | Pharmacy adapter |
| **Sensitivity** | Operational |
| **Schema version** | 1 (migration 0001) |
| **Notes** | From the formulary plus the nightly CSV. |

## Checks

- qty >= 0
- as_of is no older than one day once the CSV feed runs
