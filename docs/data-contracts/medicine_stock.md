# medicine_stock

| | |
|---|---|
| **Owner** | Pharmacy adapter |
| **Sensitivity** | Operational |
| **Schema version** | 1 (migration 0001) |
| **Notes** | From the formulary plus the nightly CSV. |

## Checks

- qty >= 0
- as_of is no older than 7 days (`STALE_AFTER_DAYS` in `sahyog/scribe/stock.py`); older stock keeps its status and is shown with its age and "(stale)"

## Freshness

Nightly CSV today; stock age shown.

## Consumers, and what breaks for each

W3 stock_check. If the schema changes: the CSV adapter's column mapping breaks, and W3's stock flags stop appearing.

## Changing the schema

A new Alembic migration, never an edit to an applied one. A breaking change (rename, drop, new meaning) needs an ADR and a version bump here first.

## Check thresholds

Every check above has a threshold of **0 violations**. Only checks backed by a database constraint, unique index or trigger are enforced. The rest hold on the seeded data by construction (a few are tested in `tests/test_seed.py`). Nothing measures them on live data yet.

