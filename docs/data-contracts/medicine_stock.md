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

## Freshness

Nightly CSV today; stock age shown.

## Consumers, and what breaks for each

W3 stock_check. If the schema changes: a stale file shows old stock: flags only, never blocks.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Uniqueness and ranges are enforced by the database where possible; the rest by `tests/test_schema.py`, `tests/test_seed.py` and the seed.

