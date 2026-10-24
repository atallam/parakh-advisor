"""Load config/instruments.yaml: the user-maintained map from holding to data-source names."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class Instrument(BaseModel):
    symbol: str | None = None
    screener: str | None = None  # India: company name in the Screener export
    edgar: str | None = None  # US: ticker for SEC EDGAR
    sector: str | None = None
    profile: str = "standard"
    conviction: str = "unset"  # core | standard | starter | tracking: yours to set. Unset = no position-size advice, only the concentration cap applies
    valuation_history_reliable: bool = True


def load_instruments(path: str | Path = "config/instruments.yaml") -> dict[str, Instrument]:
    p = Path(path)
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {str(k): Instrument(**v) for k, v in raw.items()}
