"""Read a Screener.in "Export to Excel" workbook (Data Sheet, format v2.1).

The export is the user's own download. We key on the COMPANY NAME cell, never the file name
(downloads get random prefixes). All money is in Rs crore, as exported. Nothing is estimated here:
a missing line is simply absent, and `metrics/quality.py` says "n/a" instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl

SECTIONS = {
    "PROFIT & LOSS": "annual",
    "Quarters": "quarters",
    "BALANCE SHEET": "balance",
    "CASH FLOW:": "cashflow",
    "PRICE:": "price",
    "DERIVED:": "derived",
}


class ScreenerError(ValueError):
    """The workbook is not a Screener export we can read."""


@dataclass
class Table:
    """Dated series: `dates[i]` pairs with `rows[label][i]`; None where the sheet is blank."""

    dates: list[date] = field(default_factory=list)
    cols: list[int] = field(
        default_factory=list
    )  # sheet column of each date (blank years are skipped)
    rows: dict[str, list[float | None]] = field(default_factory=dict)

    def get(self, label: str) -> list[float | None]:
        return self.rows.get(label, [None] * len(self.dates))


@dataclass
class ScreenerCompany:
    name: str
    version: str
    price: float | None
    market_cap: float | None  # Rs crore
    face_value: float | None
    annual: Table
    quarters: Table
    balance: Table
    cashflow: Table
    year_end_price: Table  # PRICE row, one value per annual date
    derived: Table
    source_file: str = ""
    money_unit: str = "Rs cr"


def _num(v: object) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_date(v: object) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def read_screener(path: str | Path) -> ScreenerCompany:
    path = Path(path)
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    except Exception as exc:  # corrupt or not xlsx
        raise ScreenerError(f"{path.name}: cannot open workbook ({exc})") from exc
    if "Data Sheet" not in wb.sheetnames:
        raise ScreenerError(f"{path.name}: no 'Data Sheet' tab; is this a Screener export?")
    grid = [list(r) for r in wb["Data Sheet"].iter_rows(values_only=True)]

    name = str(grid[0][1] or "").strip() if grid and len(grid[0]) > 1 else ""
    if not name:
        raise ScreenerError(f"{path.name}: COMPANY NAME cell is empty")

    meta: dict[str, object] = {}
    tables: dict[str, Table] = {k: Table() for k in SECTIONS.values()}
    year_end = Table()
    current: Table | None = None
    section = ""
    seen: dict[str, int] = {}
    for row in grid[1:]:
        label = row[0]
        if label is None:
            continue
        label = str(label).strip()
        if label == "META":
            section = "meta"
            current = None
            continue
        if label in SECTIONS:
            section = SECTIONS[label]
            current = tables[section]
            seen = {}
            if section == "price":  # PRICE: carries values on its own row
                ann = tables["annual"]
                year_end = Table(
                    dates=list(ann.dates),
                    cols=list(ann.cols),
                    rows={"Price": [_num(row[i]) if i < len(row) else None for i in ann.cols]},
                )
            continue
        if section == "meta":
            meta[label] = row[1]
            continue
        if current is None or section == "price":
            continue
        if (
            section == "derived" and not current.cols
        ):  # DERIVED has no date row: shares line up with annual columns
            current.dates, current.cols = list(tables["annual"].dates), list(tables["annual"].cols)
        if label == "Report Date":
            pairs = [(i + 1, _as_date(v)) for i, v in enumerate(row[1:])]
            current.cols = [i for i, d in pairs if d]
            current.dates = [d for _, d in pairs if d]
            continue
        seen[label] = seen.get(label, 0) + 1
        key = label if seen[label] == 1 else f"{label} #{seen[label]}"
        current.rows[key] = [_num(row[i]) if i < len(row) else None for i in current.cols]

    return ScreenerCompany(
        name=name,
        version=str(meta.get("CURRENT VERSION") or ""),
        price=_num(meta.get("Current Price")),
        market_cap=_num(meta.get("Market Capitalization")),
        face_value=_num(meta.get("Face Value")),
        annual=tables["annual"],
        quarters=tables["quarters"],
        balance=tables["balance"],
        cashflow=tables["cashflow"],
        year_end_price=year_end,
        derived=tables["derived"],
        source_file=path.name,
    )


def load_folder(folder: str | Path) -> dict[str, ScreenerCompany]:
    """All `*.xlsx` in a folder, keyed by upper-cased company name. Unreadable files are skipped loudly."""
    out: dict[str, ScreenerCompany] = {}
    for f in sorted(Path(folder).glob("*.xlsx")):
        try:
            c = read_screener(f)
        except ScreenerError as exc:
            print(f"warning: {exc}")
            continue
        out[c.name.upper()] = c
    return out
