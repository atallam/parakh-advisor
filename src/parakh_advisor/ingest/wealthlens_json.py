"""Read a WealthLens `holdings` JSON export (milestone 1 transport).

Phase 2 replaces this with a read-only Supabase view; the rest of the system only sees
`Portfolio`, so nothing else changes.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from parakh_advisor.sources.fx import get_usd_inr
from parakh_advisor.sources.http import SourceError

REQUIRED_KEYS = ("id", "type", "member_id")


_ISIN = re.compile(r"^IN[EF][A-Z0-9]{9}$")

# WealthLens "Export holdings" CSV header -> the key the JSON export uses.
_CSV_COLUMNS = {
    "Name": "name",
    "Type": "type",
    "Member ID": "member_id",
    "Ticker": "ticker",
    "Net Units": "units",
    "Avg Cost (INR)": "avg_cost",
    "Current Value (INR)": "current_value",
    "Principal": "principal",
    "Interest Rate %": "interest_rate",
    "Currency": "currency",
    "Start Date": "start_date",
    "Maturity Date": "maturity_date",
    "Source": "source",
}


class ExportError(ValueError):
    """The file is not a usable WealthLens holdings export."""


def _csv_row(raw: dict[str, str], index: int) -> dict[str, Any]:
    """Map one CSV row to the JSON shape. The CSV has no row id, no ISIN column and no price.

    ISIN is read from `Ticker` (funds, bonds) or `Scheme Code` (stocks); the CSV's
    `Scheme Code` stays the AMFI code for funds. Prices are absent, so value comes from
    `Current Value`.
    """
    row: dict[str, Any] = {key: (raw.get(col) or "").strip() for col, key in _CSV_COLUMNS.items()}
    ticker, code = row.get("ticker", ""), (raw.get("Scheme Code") or "").strip()
    if _ISIN.match(ticker):
        row["isin"], row["scheme_code"] = ticker, code
    elif _ISIN.match(code):
        row["isin"], row["scheme_code"] = code, ""
    else:
        row["isin"], row["scheme_code"] = "", code
    row["id"] = f"csv:{row['member_id']}:{row['isin'] or ticker or row['name']}:{index}"
    return row


def _load_csv(p: Path, usd_inr: Callable[[], float] | None = None) -> list[dict[str, Any]]:
    """Read the CSV export. US rows are in USD and the CSV carries no exchange rate, so the rate
    comes from `sources.fx` (override with `PARAKH_USD_INR`). Only fetched when USD rows exist."""
    from dotenv import load_dotenv

    load_dotenv()
    with p.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in ("Name", "Type", "Member ID") if c not in (reader.fieldnames or [])]
        if missing:
            raise ExportError(f"{p.name} is missing CSV columns: {', '.join(missing)}")
        rows = [_csv_row(r, i) for i, r in enumerate(reader)]
    usd_rows = [r for r in rows if r.get("currency", "").upper() == "USD"]
    if usd_rows:
        if usd_inr is None:
            usd_inr = _default_usd_inr
        try:
            rate = usd_inr()
        except SourceError as exc:
            raise ExportError(f"{p.name} has USD rows and no exchange rate: {exc}") from exc
        for r in usd_rows:
            r["usd_inr_rate"] = str(rate)
    return rows


def _default_usd_inr() -> float:
    return get_usd_inr().rate


def load_rows(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise ExportError(f"Input file not found: {p}")
    if p.suffix.lower() == ".csv":
        data: Any = _load_csv(p)
    else:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ExportError(f"{p.name} is not valid JSON: {exc}") from exc
    if isinstance(data, dict):  # tolerate {"data": [...]} / {"holdings": [...]}
        data = data.get("data") or data.get("holdings")
    if not isinstance(data, list) or not data:
        raise ExportError("Expected a non-empty JSON list of holdings rows.")
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            raise ExportError(f"Row {i} is not an object.")
        missing = [k for k in REQUIRED_KEYS if k not in row]
        if missing:
            raise ExportError(f"Row {i} is missing required keys: {', '.join(missing)}")
    return data


def num(value: Any) -> float | None:
    """WealthLens stores numbers as strings. Return None for blank or non-numeric."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def positive(value: Any) -> float | None:
    """Like `num` but treats 0 as missing: a zero cost means 'unknown', not 'free'."""
    n = num(value)
    return n if n is not None and n > 0 else None


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    s = str(value).strip().replace(" ", "T", 1)
    if s.endswith("+00"):
        s += ":00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def parse_date(value: Any) -> date | None:
    dt = parse_dt(value)
    return dt.date() if dt else None
