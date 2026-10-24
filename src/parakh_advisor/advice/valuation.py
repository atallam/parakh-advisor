"""Valuation stance. Version 1 uses the stock's trailing P/E against its own 5-year median only.

That is a weak anchor (own history, year-end prices) and the basis string says so. Reverse-DCF and
sector percentiles replace it later; until then NA is the honest answer whenever the input is missing
or known to be distorted (for example HDFC Bank after the 2023 merger).
"""

from __future__ import annotations

from parakh_advisor.metrics.quality import CompanyMetrics


def valuation_stance(m: CompanyMetrics | None, history_reliable: bool = True) -> tuple[str, str]:
    if m is None:
        return "NA", "no fundamentals loaded"
    x = m.get("pe_vs_hist")
    if not history_reliable:
        return "NA", "own-history P/E is distorted for this company (merger or restructuring)"
    if x is None or x.value is None:
        return "NA", x.note if x and x.note else "no usable P/E history"
    v = x.value
    stance = "CHEAP" if v < -20 else "FAIR" if v <= 20 else "RICH" if v <= 40 else "STRETCHED"
    return (
        stance,
        f"{x.basis}: {v:+.0f}% (history only; no sector or growth adjustment yet)",
    )
