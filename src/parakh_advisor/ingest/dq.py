"""Data-quality rules. Each one produces a visible flag; none fixes the data silently.

DQ-01 cost missing or zero        DQ-05 BSE listing (vs NSE)
DQ-02 position older than 30 days DQ-06 fund scheme name unresolved
DQ-03 price older than 3 days     DQ-07 shared corporate lineage (e.g. a demerger)
DQ-04 cost/price ratio implausible DQ-08 WealthLens asset_class is null
DQ-09 fund held in the Regular plan
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from parakh_advisor.contracts.holdings_v2 import (
    DIRECT_STOCKS,
    AssetClass,
    DQFlag,
    Position,
    Severity,
)

POSITION_STALE_DAYS = 30
PRICE_STALE_DAYS = 3
COST_RATIO_HIGH = 10.0
COST_RATIO_LOW = 0.1

# Generic fund names that do not identify a scheme, e.g. "INVESCO MUTUAL FUND".
_GENERIC_FUND = re.compile(r"^[A-Z0-9 &.]+ MUTUAL FUND$")
# Names that share a lineage after a corporate action. Extend as needed.
_LINEAGE_GROUPS = {"TATA MOTORS": "Tata Motors demerger (passenger vs commercial vehicles)"}


def _needs_cost(p: Position) -> bool:
    return p.asset_class in (
        AssetClass.IN_EQUITY,
        AssetClass.US_EQUITY,
        AssetClass.FUND,
        AssetClass.ETF,
    )


def run_checks(
    positions: list[Position], raw_rows: list[dict[str, Any]], ref: date
) -> list[DQFlag]:
    flags: list[DQFlag] = []
    for p in positions:
        iid = p.instrument_id
        if _needs_cost(p) and p.cost_per_unit is None:
            flags.append(
                DQFlag(
                    code="DQ-01",
                    severity=Severity.INFO,
                    instrument_id=iid,
                    message=f"{p.name}: cost pending (no usable cost basis in WealthLens).",
                )
            )
        if p.position_as_of and _needs_cost(p):
            age = (ref - p.position_as_of).days
            if age > POSITION_STALE_DAYS:
                flags.append(
                    DQFlag(
                        code="DQ-02",
                        severity=Severity.WARN,
                        instrument_id=iid,
                        message=f"{p.name}: quantity is {age} days old ({p.source}, as of {p.position_as_of}).",
                    )
                )
        if p.price_as_of and _needs_cost(p):
            age = (ref - p.price_as_of.date()).days
            if age > PRICE_STALE_DAYS:
                flags.append(
                    DQFlag(
                        code="DQ-03",
                        severity=Severity.WARN,
                        instrument_id=iid,
                        message=f"{p.name}: price is {age} days old.",
                    )
                )
        if p.cost_per_unit and p.price:
            ratio = p.price / p.cost_per_unit
            if ratio > COST_RATIO_HIGH or ratio < COST_RATIO_LOW:
                flags.append(
                    DQFlag(
                        code="DQ-04",
                        severity=Severity.WARN,
                        instrument_id=iid,
                        message=(
                            f"{p.name}: price is {ratio:.1f}x the recorded cost per unit "
                            f"({p.cost_per_unit:g} -> {p.price:g}). Possibly split-adjusted "
                            f"or mis-entered cost. Please verify."
                        ),
                    )
                )
        if p.asset_class == AssetClass.IN_EQUITY and p.exchange == "BSE":
            flags.append(
                DQFlag(
                    code="DQ-05",
                    severity=Severity.INFO,
                    instrument_id=iid,
                    message=f"{p.name}: tracked on BSE ({p.symbol}.BO); NSE listing preferred for data.",
                )
            )
        if (
            p.asset_class in (AssetClass.FUND, AssetClass.ETF)
            and not p.resolved
            and _GENERIC_FUND.match(p.name)
        ):
            flags.append(
                DQFlag(
                    code="DQ-06",
                    severity=Severity.WARN,
                    instrument_id=iid,
                    message=f"{p.name}: scheme name not specific; resolve via ISIN {p.isin or 'n/a'} against AMFI.",
                )
            )
    # DQ-09: regular plan (informational; direct plans carry a lower expense ratio)
    for p in positions:
        if p.asset_class == AssetClass.FUND and p.plan == "Regular":
            flags.append(
                DQFlag(
                    code="DQ-09",
                    severity=Severity.INFO,
                    instrument_id=p.instrument_id,
                    message=f"{p.name}: held in the Regular plan; the Direct plan of the same scheme has a lower expense ratio.",
                )
            )
    # DQ-07 lineage: more than one direct stock whose name starts with a known group
    for stem, note in _LINEAGE_GROUPS.items():
        members = [
            p
            for p in positions
            if p.asset_class in DIRECT_STOCKS and p.name.upper().startswith(stem)
        ]
        if len(members) > 1:
            names = ", ".join(sorted({p.symbol or p.name for p in members}))
            flags.append(
                DQFlag(
                    code="DQ-07",
                    severity=Severity.INFO,
                    instrument_id=None,
                    message=f"{names}: {note}. Treated as separate businesses with limited history.",
                )
            )
    # DQ-08 once: WealthLens asset_class is null on every row
    if raw_rows and all(not r.get("asset_class") for r in raw_rows):
        flags.append(
            DQFlag(
                code="DQ-08",
                severity=Severity.INFO,
                instrument_id=None,
                message="WealthLens asset_class is empty on every row; Parakh derives asset class and sector itself.",
            )
        )
    return flags
