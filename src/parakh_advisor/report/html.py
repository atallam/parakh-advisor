"""Render the portfolio snapshot as one self-contained HTML page.

This page is the design prototype for the future WealthLens "Advisory" tab: same sections,
same order, so porting it to React is mechanical.
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from parakh_advisor.advice.snapshot import Snapshot
from parakh_advisor.contracts.holdings_v2 import CONTEXT_ASSETS, Severity

TEMPLATE_DIR = Path(__file__).parent / "templates"


def inr(value: float | None) -> str:
    """Indian digit grouping: 1234567 -> ₹12,34,567."""
    if value is None:
        return "n/a"
    n = int(round(value))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = f"{head},{tail}"
    return f"₹{'-' if n < 0 else ''}{s}"


def lakh(value: float | None) -> str:
    return "n/a" if value is None else f"₹{value / 1e5:,.2f} L"


_CLASS_LABELS = {
    "US_EQUITY": "US stocks",
    "IN_EQUITY": "Indian stocks",
    "FUND": "Mutual funds",
    "ETF": "ETFs",
    "COMMODITY ETF": "Gold ETF",
    "FD": "Fixed deposits",
    "PPF": "PPF",
    "EPF": "EPF",
    "INSURANCE": "Insurance",
    "CASH": "Cash",
    "OTHER": "Other",
}


def class_label(value: str) -> str:
    return _CLASS_LABELS.get(str(value), str(value).replace("_", " ").title())


def health_lines(snapshot: Snapshot) -> list[str]:
    """Collapse repeated flags into a few readable lines (details stay in the notes list)."""
    lines: list[str] = []
    stale = [f for f in snapshot.flags if f.code == "DQ-02"]
    if stale:
        lines.append(
            f"{len(stale)} positions have quantities older than 30 days "
            f"(synced {snapshot.oldest_position_as_of} to {snapshot.newest_position_as_of}). "
            "Advice is only as current as that sync."
        )
    if snapshot.cost_pending_count:
        total = snapshot.cost_pending_count + snapshot.cost_tracked_count
        lines.append(
            f"Cost basis is pending for {snapshot.cost_pending_count} of {total} positions, "
            "so their profit/loss is blank rather than guessed."
        )
    funds = [f for f in snapshot.flags if f.code == "DQ-06"]
    if funds:
        lines.append(
            f"{len(funds)} funds have a generic name that does not identify the scheme; they will be resolved by ISIN."
        )
    for f in snapshot.flags:
        if f.code in ("DQ-03", "DQ-04"):
            lines.append(f.message)
    if snapshot.acknowledged_flags:
        lines.append("Checked and accepted by you: " + "; ".join(snapshot.acknowledged_flags) + ".")
    return lines


def render_snapshot(
    snapshot: Snapshot,
    generated_for: str = "",
    alerts: list | None = None,
    notices: list[str] | None = None,
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["inr"] = inr
    env.filters["lakh"] = lakh
    env.filters["class_label"] = class_label

    equity_like = [h for h in snapshot.holdings if h.weight_pct is not None]
    context = [h for h in snapshot.holdings if h.asset_class in CONTEXT_ASSETS]
    other = [
        h for h in snapshot.holdings if h.weight_pct is None and h.asset_class not in CONTEXT_ASSETS
    ]
    max_w = max([h.weight_pct for h in equity_like] + [snapshot.policy_single_cap * 1.5])
    warns = [f for f in snapshot.flags if f.severity == Severity.WARN]
    infos = [f for f in snapshot.flags if f.severity == Severity.INFO]
    return env.get_template("portfolio.html.j2").render(
        notices=notices or [],
        s=snapshot,
        equity_like=equity_like,
        context=context,
        other=other,
        max_w=max_w,
        cap_pos=snapshot.policy_single_cap / max_w * 100,
        warns=warns,
        infos=infos,
        health=health_lines(snapshot),
        generated_for=generated_for,
        alerts=alerts or [],
        alerts_checked=alerts is not None,
    )
