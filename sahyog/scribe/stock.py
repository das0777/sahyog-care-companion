"""Stock lookup behind one interface: a CSV today, a pharmacy API later (spec, Tools)."""

import csv
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from rapidfuzz import fuzz

LOW_BELOW = 20
STALE_AFTER_DAYS = 7
MATCH = 88


@dataclass(frozen=True)
class StockLine:
    status: str  # in_stock | low | out | unknown
    qty: int | None
    as_of: str | None
    age_days: int | None
    medicine_id: str | None
    matched: str | None
    stale: bool = False


UNKNOWN = StockLine("unknown", None, None, None, None, None)


class StockSource(Protocol):
    def lookup(self, medicine: str, dose: str, clinic_id: str) -> StockLine: ...


class CsvStockAdapter:
    def __init__(self, path: Path, *, today: date | None = None):
        self.path = Path(path)
        self.today = today

    @lru_cache(maxsize=1)  # noqa: B019 - one adapter per process; a new file means a new adapter
    def _rows(self) -> tuple[dict, ...]:
        if not self.path.exists():
            return ()
        with self.path.open() as f:
            return tuple(csv.DictReader(f))

    def lookup(self, medicine: str, dose: str, clinic_id: str) -> StockLine:
        """Molecule and dose must both match, or the answer is unknown: telling a pharmacist that
        a 10 mg strength is in stock when the doctor said 20 mg would be worse than not knowing."""
        wanted = medicine.lower().strip()
        strength = _number(dose)
        best = None
        for row in self._rows():
            if row["clinic_id"] != clinic_id:
                continue
            name = row["composition"].lower()
            if fuzz.partial_ratio(wanted, name) < MATCH:
                continue
            if strength and _number(name) != strength:
                continue
            best = row
            break
        if best is None:
            return UNKNOWN
        qty = int(best["qty"])
        as_of = date.fromisoformat(best["as_of"])
        age = max(((self.today or date.today()) - as_of).days, 0)
        status = "out" if qty <= 0 else "low" if qty < LOW_BELOW else "in_stock"
        return StockLine(
            status,
            qty,
            best["as_of"],
            age,
            best["medicine_id"],
            best["composition"],
            age > STALE_AFTER_DAYS,
        )


def _number(text: str) -> str | None:
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return m.group(0) if m else None
