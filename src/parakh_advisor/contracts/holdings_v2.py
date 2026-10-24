"""Contract `holdings.v2`: what Parakh Advisor needs from WealthLens, after normalisation.

WealthLens owns holdings; Parakh only reads them. Every field here is derived from the
WealthLens `holdings` table (see docs: section 9.2 of the system design).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AssetClass(StrEnum):
    IN_EQUITY = "IN_EQUITY"
    US_EQUITY = "US_EQUITY"
    FUND = "FUND"
    ETF = "ETF"
    FD = "FD"
    PPF = "PPF"
    EPF = "EPF"
    INSURANCE = "INSURANCE"
    CASH = "CASH"
    OTHER = "OTHER"


class ValueBasis(StrEnum):
    MARKET = "market"  # units x live price
    PRINCIPAL = "principal"  # FD/PPF/EPF: amount invested, not a market value
    REPORTED = "reported"  # value reported by the source (e.g. insurance)
    UNKNOWN = "unknown"


class Severity(StrEnum):
    INFO = "info"
    WARN = "warn"


# Direct single stocks: the only positions that get a single-name cap and a thesis.
DIRECT_STOCKS = frozenset({AssetClass.IN_EQUITY, AssetClass.US_EQUITY})
# Context assets: counted in net worth, never advised on.
CONTEXT_ASSETS = frozenset(
    {AssetClass.FD, AssetClass.PPF, AssetClass.EPF, AssetClass.INSURANCE, AssetClass.CASH}
)


class DQFlag(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str  # DQ-01 ... DQ-08
    severity: Severity
    instrument_id: str | None = None
    message: str


class Position(BaseModel):
    """One WealthLens row, normalised. Not yet merged across members."""

    model_config = ConfigDict(frozen=True)

    source_row_id: str
    member_id: str
    instrument_id: str  # ISIN for India and funds, "US:<TICKER>" for US stocks
    name: str
    asset_class: AssetClass
    sleeve: str = "equity"  # "equity" or "commodity" (gold ETF)
    symbol: str | None = None
    isin: str | None = None
    exchange: str | None = None  # NSE, BSE, US
    currency: str = "INR"
    units: float = 0.0
    price: float | None = None  # native currency
    fx_to_inr: float | None = None  # 1.0 for INR
    value_inr: float | None = None
    value_basis: ValueBasis = ValueBasis.UNKNOWN
    cost_per_unit: float | None = None  # native currency; None means "cost pending", never 0
    cost_value_inr: float | None = None
    position_as_of: date | None = None
    price_as_of: datetime | None = None
    source: str = "unknown"  # cas | snaptrade | manual
    account_label: str | None = None
    scheme_code: str | None = None
    category: str | None = None  # funds: SEBI category from AMFI/mfapi
    plan: str | None = None  # funds: "Direct" | "Regular"
    resolved: bool = False  # fund scheme resolved against AMFI

    @property
    def is_listed_equity(self) -> bool:
        """Counts in the concentration denominator (US + India stocks and equity funds)."""
        if self.asset_class in (AssetClass.IN_EQUITY, AssetClass.US_EQUITY, AssetClass.FUND):
            return True
        return self.asset_class == AssetClass.ETF and self.sleeve == "equity"


class Portfolio(BaseModel):
    model_config = ConfigDict(frozen=True)

    positions: list[Position] = Field(default_factory=list)
    flags: list[DQFlag] = Field(default_factory=list)
    reference_date: date  # "data as of": the newest price timestamp in the export
    usd_inr: float | None = None
