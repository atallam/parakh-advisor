"""Reverse DCF: what growth does today's market value ask for?

Instead of forecasting a price, solve for the yearly profit growth that, held for 10 years and
followed by a terminal growth rate, discounts back to today's market value. Then compare that with
what the company has actually delivered. No forecast is made by the code; the only inputs are the
market value, the profit base, a discount rate and a terminal rate (assumptions, stated in the basis).

Assumptions (design V2-19): US 10% discount, 3% terminal; India 15% discount, 5% terminal.
Profit stands in for free cash flow (capex is not available for every company); that flatters
capital-heavy businesses, which the note says.
"""

from __future__ import annotations

YEARS = 10
LO, HI = -0.30, 0.80  # search range for yearly growth
REFERENCE_CAP = 25.0  # past growth above this is not credited as sustainable for 10 years

RATES = {"US": (0.10, 0.03), "IN": (0.15, 0.05)}


def present_value(base: float, g: float, r: float, tg: float, years: int = YEARS) -> float:
    pv, e = 0.0, base
    for t in range(1, years + 1):
        e *= 1 + g
        pv += e / (1 + r) ** t
    return pv + e * (1 + tg) / (r - tg) / (1 + r) ** years


def implied_growth(
    market_value: float, base: float, r: float, tg: float, years: int = YEARS
) -> tuple[float, str | None]:
    """Yearly growth (as a fraction) that makes the discounted profits equal the market value.
    Returns (growth, edge) where edge is "low"/"high" when the answer sits at the search limit."""
    if present_value(base, LO, r, tg, years) >= market_value:
        return LO, "low"
    if present_value(base, HI, r, tg, years) <= market_value:
        return HI, "high"
    lo, hi = LO, HI
    for _ in range(80):
        mid = (lo + hi) / 2
        if present_value(base, mid, r, tg, years) < market_value:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2, None


def market_of(money_unit: str) -> str:
    return "US" if money_unit.upper().startswith("USD") else "IN"


def profit_base(fy_profit: float | None, ttm_profit: float | None) -> tuple[float | None, str]:
    """The lower of last fiscal year and trailing four quarters, so a one-off high cannot make the
    market's ask look small. Both must be positive when both exist."""
    cands = [
        (v, n)
        for v, n in ((fy_profit, "last fiscal year"), (ttm_profit, "trailing 4 quarters"))
        if v is not None
    ]
    if not cands or any(v <= 0 for v, _ in cands):
        return None, "profit not positive"
    v, n = min(cands)
    return v, n


def stance_from_gap(implied_pct: float, gap_pp: float | None) -> str:
    """CHEAP: the market asks for 8+ points a year less than the company has delivered.
    FAIR: within -8 to +5. RICH: 5 to 12 above. STRETCHED: 12+ above, or any ask above 25% a year
    for ten years (profit would grow tenfold)."""
    if implied_pct > 25:
        return "STRETCHED"
    if gap_pp is None:
        return "NA"
    if gap_pp <= -8:
        return "CHEAP"
    if gap_pp < 5:
        return "FAIR"
    if gap_pp < 12:
        return "RICH"
    return "STRETCHED"
