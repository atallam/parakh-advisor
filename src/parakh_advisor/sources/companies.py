"""One place that turns instruments.yaml + your files + live sources into fundamentals per holding.

India: a Screener export in data/inbox/screener (matched by company name).
US: SEC EDGAR company facts (cached 7 days), priced from your WealthLens price.
A holding whose source fails is skipped with a message, never silently dropped.
"""

from __future__ import annotations

import sys
from pathlib import Path

from parakh_advisor.contracts.holdings_v2 import Portfolio
from parakh_advisor.ingest.instruments import Instrument
from parakh_advisor.sources.http import SourceError
from parakh_advisor.sources.india.screener_export import ScreenerCompany, load_folder
from parakh_advisor.sources.us.edgar import Edgar


def load_companies(
    instruments: dict[str, Instrument],
    screener_dir: str | Path,
    portfolio: Portfolio | None,
    cache_dir: str | Path = "data/cache",
    use_edgar: bool = True,
    failures: list[str] | None = None,
) -> dict[str, ScreenerCompany]:
    india = load_folder(screener_dir) if Path(screener_dir).exists() else {}
    prices = {p.instrument_id: p.price for p in portfolio.positions} if portfolio else {}
    names = {p.instrument_id: p.name for p in portfolio.positions} if portfolio else {}
    edgar = Edgar(cache_dir)
    out: dict[str, ScreenerCompany] = {}
    for iid, inst in instruments.items():
        label = inst.symbol or iid
        try:
            if inst.edgar:
                if not use_edgar:
                    continue
                out[iid] = edgar.company(
                    inst.edgar, names.get(iid) or inst.symbol or iid, prices.get(iid)
                )
            elif inst.screener:
                c = india.get(inst.screener.upper())
                if c is None:
                    msg = f"{label}: no Screener export named '{inst.screener}' in {screener_dir}"
                    print(f"  - {msg}", file=sys.stderr)
                    if failures is not None:
                        failures.append(msg)
                    continue
                out[iid] = c
        except SourceError as exc:
            msg = f"{label}: fundamentals unavailable ({exc})"
            print(f"  - {msg}", file=sys.stderr)
            if failures is not None:
                failures.append(msg)
    return out
