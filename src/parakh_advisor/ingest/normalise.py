"""Turn raw WealthLens rows into normalised `Position`s.

Rules (design section 9.2): ISIN is the identity key for India and funds, `US:<TICKER>`
for US stocks. Zero cost means "cost pending". Nothing is silently corrected: oddities are
left as they are and reported by `dq.py`.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable
from datetime import date
from typing import Any

from parakh_advisor.contracts.holdings_v2 import (
    AssetClass,
    Portfolio,
    Position,
    ValueBasis,
)
from parakh_advisor.ingest.dq import run_checks
from parakh_advisor.ingest.wealthlens_json import num, parse_date, parse_dt, positive
from parakh_advisor.sources.funds.mfapi import FundMeta

_TYPE_MAP = {
    "IN_STOCK": AssetClass.IN_EQUITY,
    "US_STOCK": AssetClass.US_EQUITY,
    "IN_ETF": AssetClass.ETF,
    "US_ETF": AssetClass.ETF,
    "MF": AssetClass.FUND,
    "FD": AssetClass.FD,
    "PPF": AssetClass.PPF,
    "EPF": AssetClass.EPF,
    "INSURANCE": AssetClass.INSURANCE,
    "CASH": AssetClass.CASH,
}
_ETF_NAME = re.compile(r"EXCHANGE TRADED|\bETF\b", re.I)
_COMMODITY_NAME = re.compile(r"\bGOLD\b|\bSILVER\b", re.I)


def clean_name(name: str) -> str:
    """`INDIAN ENERGY EXCHANGE LIMITED#NEW` -> `INDIAN ENERGY EXCHANGE LIMITED`."""
    s = re.sub(r"#.*$", "", name or "")
    s = re.sub(r"\s*-+\s*$", "", s)
    return re.sub(r"\s+", " ", s).strip()


def classify(row: dict[str, Any]) -> tuple[AssetClass, str]:
    """Return (asset class, sleeve). A gold ETF typed `MF` becomes ETF + commodity."""
    cls = _TYPE_MAP.get(str(row.get("type", "")).upper(), AssetClass.OTHER)
    name = str(row.get("name") or "")
    sleeve = "equity"
    if cls == AssetClass.FUND and _ETF_NAME.search(name):
        cls = AssetClass.ETF
    if cls == AssetClass.ETF and _COMMODITY_NAME.search(name):
        sleeve = "commodity"
    return cls, sleeve


def split_ticker(ticker: str | None) -> tuple[str | None, str | None]:
    """`M&M.NS` -> (`M&M`, `NSE`); `MAZDOCK.BO` -> (`MAZDOCK`, `BSE`)."""
    if not ticker:
        return None, None
    t = ticker.strip()
    if t.upper().endswith(".NS"):
        return t[:-3], "NSE"
    if t.upper().endswith(".BO"):
        return t[:-3], "BSE"
    return t, None


def _position_as_of(row: dict[str, Any]) -> date | None:
    source = str(row.get("source") or "").lower()
    if source == "cas":
        return parse_date(row.get("source_date")) or parse_date(row.get("cas_period_end"))
    if source == "snaptrade":
        return parse_date(row.get("last_synced"))
    return parse_date(row.get("updated_at"))


def _median_usd_inr(rows: list[dict[str, Any]]) -> float | None:
    rates = [r for r in (positive(x.get("usd_inr_rate")) for x in rows) if r]
    return statistics.median(rates) if rates else None


def normalise_row(row: dict[str, Any], usd_inr: float | None) -> Position:
    cls, sleeve = classify(row)
    is_us = cls == AssetClass.US_EQUITY or (
        cls == AssetClass.ETF and str(row.get("type", "")).upper() == "US_ETF"
    )
    currency = str(row.get("currency") or ("USD" if is_us else "INR")).upper()
    fx = 1.0 if currency == "INR" else (positive(row.get("usd_inr_rate")) or usd_inr)

    symbol, exchange = split_ticker(row.get("ticker"))
    isin = (row.get("isin") or "").strip() or None
    if is_us:
        exchange = "US"
        instrument_id = f"US:{(row.get('ticker') or '').strip().upper()}"
        symbol = (row.get("ticker") or "").strip().upper()
    elif cls in (AssetClass.IN_EQUITY, AssetClass.FUND, AssetClass.ETF) and isin:
        instrument_id = isin
    else:
        instrument_id = isin or (row.get("ticker") or "").strip() or str(row["id"])

    if cls in (AssetClass.FUND, AssetClass.ETF) and not is_us:
        symbol = None  # a fund's "ticker" is its ISIN; show the scheme name instead

    units = num(row.get("units")) or 0.0
    price = positive(row.get("current_price")) or positive(row.get("current_nav"))

    value_native: float | None
    basis = ValueBasis.UNKNOWN
    if cls in (AssetClass.FD, AssetClass.PPF, AssetClass.EPF):
        value_native, basis = positive(row.get("principal")), ValueBasis.PRINCIPAL
    elif cls == AssetClass.INSURANCE:
        value_native, basis = positive(row.get("current_value")), ValueBasis.REPORTED
    elif cls == AssetClass.CASH:
        value_native = (price * units) if price else None
        basis = ValueBasis.MARKET
    else:
        value_native = positive(row.get("current_value")) or ((price * units) if price else None)
        basis = ValueBasis.MARKET if value_native else ValueBasis.UNKNOWN
    value_inr = value_native * fx if (value_native is not None and fx) else None

    # Cost per unit in native currency. avg_cost wins; zero/null means pending.
    cost_unit = positive(row.get("avg_cost")) or positive(row.get("purchase_price"))
    if cost_unit is None and cls == AssetClass.FUND:
        cost_unit = positive(row.get("purchase_nav"))
    if cls in (
        AssetClass.FD,
        AssetClass.PPF,
        AssetClass.EPF,
        AssetClass.INSURANCE,
        AssetClass.CASH,
    ):
        cost_unit = None
    cost_value_inr = cost_unit * units * fx if (cost_unit and units and fx) else None

    return Position(
        source_row_id=str(row["id"]),
        member_id=str(row["member_id"]),
        instrument_id=instrument_id,
        name=clean_name(str(row.get("name") or "")),
        asset_class=cls,
        sleeve=sleeve,
        symbol=symbol,
        isin=isin,
        exchange=exchange,
        currency=currency,
        units=units,
        price=price,
        fx_to_inr=fx,
        value_inr=value_inr,
        value_basis=basis,
        cost_per_unit=cost_unit,
        cost_value_inr=cost_value_inr,
        position_as_of=_position_as_of(row),
        price_as_of=parse_dt(row.get("price_fetched_at")),
        source=str(row.get("source") or "unknown").lower(),
        account_label=row.get("brokerage_name") or None,
        scheme_code=(row.get("scheme_code") or None),
    )


def apply_fund_meta(p: Position, meta: FundMeta) -> Position:
    """Replace a vague WealthLens fund row with the real scheme, category and plan."""
    update: dict[str, Any] = {
        "name": meta.scheme_name,
        "category": meta.short_category,
        "plan": meta.plan,
        "resolved": True,
    }
    if meta.is_commodity:  # gold/silver ETFs typed as funds in WealthLens
        update.update(asset_class=AssetClass.ETF, sleeve="commodity")
    elif p.asset_class == AssetClass.ETF and p.sleeve != "commodity":
        update.update(asset_class=AssetClass.ETF)
    return p.model_copy(update=update)


def build_portfolio(
    rows: list[dict[str, Any]],
    fund_resolver: Callable[[str], FundMeta | None] | None = None,
) -> Portfolio:
    """Normalise all active rows, optionally resolve funds online, then attach data-quality flags."""
    active = [r for r in rows if str(r.get("holding_status", "active")).lower() == "active"]
    usd_inr = _median_usd_inr(active)
    positions = [normalise_row(r, usd_inr) for r in active]
    if fund_resolver is not None:
        resolved: list[Position] = []
        for p in positions:
            if p.asset_class in (AssetClass.FUND, AssetClass.ETF) and p.scheme_code:
                meta = fund_resolver(p.scheme_code)
                p = apply_fund_meta(p, meta) if meta else p
            resolved.append(p)
        positions = resolved
    stamps = [p.price_as_of for p in positions if p.price_as_of]
    ref = max(stamps).date() if stamps else date.today()
    flags = run_checks(positions, active, ref)
    return Portfolio(positions=positions, flags=flags, reference_date=ref, usd_inr=usd_inr)
