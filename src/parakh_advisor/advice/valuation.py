"""Valuation stance from two independent readings; the more cautious one wins.

1. Own history: trailing P/E against the median of the stock's last five year-end P/Es.
2. Reverse DCF: the yearly profit growth today's market value asks for over ten years, against the
   growth the company has delivered (metrics/rdcf.py).

Either reading alone is weak (history rewards stocks that were always expensive; reverse DCF leans on
past growth and on the discount rate). Taking the worse of the two means a stock is called CHEAP or
FAIR only when neither reading objects. NA only when both are unreadable. No price targets.
"""

from __future__ import annotations

from parakh_advisor.metrics import rdcf
from parakh_advisor.metrics.quality import CompanyMetrics

ORDER = {"CHEAP": 0, "FAIR": 1, "RICH": 2, "STRETCHED": 3}


def _history(m: CompanyMetrics, reliable: bool) -> tuple[str, str]:
    x = m.get("pe_vs_hist")
    if not reliable:
        return "NA", "own-history P/E is distorted for this company (merger or restructuring)"
    if x is None or x.value is None:
        return "NA", x.note if x and x.note else "no usable P/E history"
    v = x.value
    stance = "CHEAP" if v < -20 else "FAIR" if v <= 20 else "RICH" if v <= 40 else "STRETCHED"
    return stance, f"{x.basis}: {v:+.0f}%"


def _reverse_dcf(m: CompanyMetrics, reliable: bool) -> tuple[str, str]:
    g, gap = m.get("rdcf_growth"), m.get("rdcf_gap")
    if g is None or g.value is None:
        return "NA", g.note if g and g.note else "no reverse DCF"
    # a distorted history (merger) also distorts the growth it is compared with: only the absolute ask counts
    use_gap = gap.value if gap is not None and reliable else None
    stance = rdcf.stance_from_gap(g.value, use_gap)
    if stance == "NA":
        return (
            "NA",
            f"market value asks for {g.value:.0f}% a year; no reliable past growth to compare",
        )
    cmp = "" if use_gap is None else f", {use_gap:+.0f} points against delivered growth"
    return stance, f"market value asks for {g.value:.0f}% a year for 10 years{cmp}"


def valuation_stance(m: CompanyMetrics | None, history_reliable: bool = True) -> tuple[str, str]:
    if m is None:
        return "NA", "no fundamentals loaded"
    h_stance, h_text = _history(m, history_reliable)
    d_stance, d_text = _reverse_dcf(m, history_reliable)
    if h_stance == "NA" and d_stance == "NA":
        return "NA", h_text if m.get("rdcf_growth") is None else f"{h_text}; {d_text}"
    if h_stance == "NA":
        return d_stance, f"Reverse DCF only ({h_text}): {d_text}"
    if d_stance == "NA":
        return h_stance, f"Own history only ({d_text}): {h_text}"
    final = max(h_stance, d_stance, key=ORDER.__getitem__)
    parts = f"own history {h_stance} ({h_text}); reverse DCF {d_stance} ({d_text})"
    if h_stance == d_stance:
        return final, f"Both readings agree: {parts}"
    return final, f"The more cautious of two readings: {parts}"
