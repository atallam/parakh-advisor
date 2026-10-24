"""Read a WealthLens `holdings` JSON export (milestone 1 transport).

Phase 2 replaces this with a read-only Supabase view; the rest of the system only sees
`Portfolio`, so nothing else changes.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

REQUIRED_KEYS = ("id", "type", "member_id")


class ExportError(ValueError):
    """The file is not a usable WealthLens holdings export."""


def load_rows(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise ExportError(f"Input file not found: {p}")
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
