"""USD to INR rate, so a CSV export (which has no rate) can value US holdings without help.

Order: `PARAKH_USD_INR` if you set it (a manual override) -> today's cached rate -> xe.com ->
ECB reference rate via Frankfurter -> open.er-api.com -> the last cached rate, if at most 7 days old. A rate
older than that is refused rather than guessed. The source and date travel with the rate.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from parakh_advisor.clock import today_ist
from parakh_advisor.sources.http import Fetcher, SourceError, http_get


def _xe(raw: bytes) -> float:
    """xe.com's converter page carries the rate as text: `1 USD = 92.9484 INR`."""
    m = re.search(rb"1\s*USD\s*=\s*([0-9][0-9,]*\.?[0-9]*)\s*INR", raw)
    if not m:
        raise ValueError("rate text not found on the page")
    return float(m.group(1).replace(b",", b""))


def _json_rate(raw: bytes) -> float:
    return float(json.loads(raw)["rates"]["INR"])


# Tried in this order. xe.com first (your choice); the other two are open APIs.
SOURCES = (
    ("xe.com", "https://www.xe.com/currencyconverter/convert/?Amount=1&From=USD&To=INR", _xe),
    (
        "ECB via Frankfurter",
        "https://api.frankfurter.dev/v1/latest?base=USD&symbols=INR",
        _json_rate,
    ),
    ("open.er-api.com", "https://open.er-api.com/v6/latest/USD", _json_rate),
)
MAX_STALE_DAYS = 7


@dataclass(frozen=True)
class FxRate:
    rate: float
    source: str
    as_of: str  # ISO date the rate was fetched (or "manual")


def get_usd_inr(cache_dir: str | Path = "data/cache", fetch: Fetcher = http_get) -> FxRate:
    manual = os.environ.get("PARAKH_USD_INR", "").strip()
    if manual:
        try:
            value = float(manual)
        except ValueError as exc:
            raise SourceError(f"PARAKH_USD_INR is not a number: {manual!r}") from exc
        if value <= 0:
            raise SourceError("PARAKH_USD_INR must be above zero")
        return FxRate(value, "PARAKH_USD_INR override", "manual")

    path = Path(cache_dir) / "fx_usd_inr.json"
    today = today_ist()
    cached: FxRate | None = None
    if path.exists():
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            cached = FxRate(float(d["rate"]), str(d["source"]), str(d["as_of"]))
        except (ValueError, KeyError, OSError):
            cached = None
    if cached and cached.as_of == today.isoformat():
        return cached

    errors: list[str] = []
    for name, url, pick in SOURCES:
        try:
            value = pick(fetch(url))
        except (SourceError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        if value <= 0:
            errors.append(f"{name}: non-positive rate")
            continue
        fresh = FxRate(value, name, today.isoformat())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"rate": fresh.rate, "source": fresh.source, "as_of": fresh.as_of}),
            encoding="utf-8",
        )
        return fresh

    if cached:
        age = today - today.fromisoformat(cached.as_of)
        if age <= timedelta(days=MAX_STALE_DAYS):
            return cached
    raise SourceError(
        "Could not get a USD/INR rate and no recent cached one exists ("
        + "; ".join(errors)
        + "). Set PARAKH_USD_INR to override."
    )
