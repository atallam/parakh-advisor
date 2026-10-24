"""Attach fund health to equity funds in a snapshot, and the category-overlap lines."""

from __future__ import annotations

from pathlib import Path

from parakh_advisor.advice.snapshot import RiskAction, Snapshot
from parakh_advisor.contracts.holdings_v2 import DIRECT_STOCKS, AssetClass
from parakh_advisor.funds.health import FundHealth, category_overlap
from parakh_advisor.funds.lookthrough import (
    FundFile,
    look_through,
    match_labels_to_funds,
    read_fund_file,
    read_fund_pdf,
)

FUND_TEXT = {
    "HEALTHY": "Ahead of its benchmark over 3 years.",
    "WATCH": "Slightly behind its benchmark over 3 years.",
    "LAGGING": "More than 3 points a year behind its benchmark over 3 years.",
    "TOO_NEW": "Under 3 years of history: too early to judge.",
    "NO_DATA": "No fund data could be loaded, so no health view.",
}


def is_equity_fund(h) -> bool:
    return h.asset_class in (AssetClass.FUND, AssetClass.ETF) and h.weight_pct is not None


def apply_fund_health(snap: Snapshot, health: dict[str, FundHealth]) -> None:
    funds = [h for h in snap.holdings if is_equity_fund(h)]
    for h in funds:
        fh = health.get(h.instrument_id)
        if fh is None:
            continue
        h.fund_status = fh.status
        h.fund_lines = fh.lines
        h.action = RiskAction.REVIEW if fh.status in ("LAGGING", "NO_DATA") else RiskAction.HOLD
        h.reason_codes = [f"FUND_{fh.status}"]
        note = FUND_TEXT[fh.status]
        if fh.direct_gap is not None and fh.direct_gap >= 0.3:
            note += f" Regular plan costing about {fh.direct_gap:.1f} points a year versus Direct."
        h.note = note
        h.would_change = {
            "HEALTHY": "Falling more than 3 points a year behind the benchmark over 3 years.",
            "WATCH": "Closing the gap (HEALTHY) or falling past 3 points a year behind (LAGGING).",
            "LAGGING": "Returns recovering to within 3 points a year of the benchmark over 3 years.",
            "TOO_NEW": "Reaching 3 years of history.",
            "NO_DATA": "Fund and benchmark NAV history becoming available.",
        }[fh.status]
        h.valuation_basis = f"Benchmark proxy: {fh.benchmark}" if fh.benchmark else ""

    rows = [(h.name, (h.category or "Unknown").split(" - ", 1)[-1], h.value_inr) for h in funds]
    snap.fund_overlap = [
        f"{len(o.names)} {o.category.lower()}s: {', '.join(n.split(' - ')[0] for n in o.names)} "
        f"= ₹{o.value_inr / 1e5:.1f} lakh, {o.pct:.1f}% of listed equity. They are different funds but "
        "buy similar kinds of company."
        for o in category_overlap(rows, snap.listed_equity_inr)
    ]
    lagging = [h.name.split(" - ")[0] for h in funds if h.fund_status == "LAGGING"]
    if lagging:
        snap.verdict.append(f"Fund(s) well behind their benchmark: {', '.join(lagging)}.")
    regular = [
        h.name.split(" - ")[0]
        for h in funds
        if h.plan == "Regular"
        and (health.get(h.instrument_id) or FundHealth(scheme_code="", status="")).direct_gap
    ]
    if regular:
        snap.verdict.append(
            f"Regular-plan funds costing you extra versus Direct: {', '.join(regular)}."
        )


def apply_lookthrough(snap: Snapshot, funds_dir: str | Path) -> list[str]:
    """Stock-level overlap from portfolio files (xlsx, csv, or a factsheet PDF) in `funds_dir`.
    Returns notices (unreadable or unmatched files, funds without a file)."""
    d = Path(funds_dir)
    paths = (
        sorted(p for p in d.glob("*") if p.suffix.lower() in (".xlsx", ".csv", ".pdf"))
        if d.exists()
        else []
    )
    if not paths:
        return []
    funds = [h for h in snap.holdings if is_equity_fund(h)]
    fund_values = {h.instrument_id: (h.name, h.value_inr) for h in funds}
    notices: list[str] = []
    cands: dict[str, FundFile] = {}  # label (file name, or scheme title inside a PDF) -> portfolio
    from_pdf: set[str] = set()
    for p in paths:
        try:
            if p.suffix.lower() == ".pdf":
                found = read_fund_pdf(p)
                cands.update(found)
                from_pdf.update(found)
            else:
                ff = read_fund_file(p)
                cands[ff.title or p.stem] = ff
        except (ValueError, OSError, KeyError, ImportError) as exc:
            notices.append(f"{p.name}: {exc}")
    matched = match_labels_to_funds(list(cands), {k: v[0] for k, v in fund_values.items()})
    notices += [
        f"{lab}: not matched to any of your funds. The file name must contain the fund's name."
        for lab in cands
        if lab not in matched.values() and lab not in from_pdf  # a factsheet covers many funds
    ]
    parsed = {}
    for iid, lab in matched.items():
        if not 50 <= cands[lab].total_pct <= 105:
            notices.append(
                f"{lab}: holdings add up to {cands[lab].total_pct:.0f}% of the fund, so the file was not used (check the file or the layout)"
            )
        else:
            parsed[iid] = cands[lab]
    if not parsed:
        return notices
    notices += [
        f"No portfolio file for {fund_values[i][0].split(' - ')[0]}"
        for i in fund_values
        if i not in parsed
    ]
    direct = {
        h.instrument_id: (h.name, h.value_inr)
        for h in snap.holdings
        if h.asset_class in DIRECT_STOCKS and h.weight_pct is not None
    }
    exposures, abroad, pairs = look_through(direct, {i: fund_values[i] for i in parsed}, parsed)
    le = snap.listed_equity_inr or 1.0
    sym = {h.instrument_id: (h.symbol or h.name) for h in snap.holdings}
    snap.lookthrough_rows = [
        {
            "symbol": sym.get(next((i for i, (n, _) in direct.items() if n == e.name), ""), e.name),
            "direct": e.direct_inr / le * 100,
            "via": e.via_funds_inr / le * 100,
            "total": e.total_inr / le * 100,
            "funds": ", ".join(f"{n.split(' - ')[0]} ({v / le * 100:.1f}%)" for n, v in e.sources),
        }
        for e in exposures[:10]
    ]
    us_direct = sum(h.value_inr for h in snap.holdings if h.asset_class == AssetClass.US_EQUITY)
    lines = [
        f"Your funds hold about ₹{abroad / 1e5:.1f} lakh ({abroad / le * 100:.1f}% of listed equity) in foreign shares. "
        f"With your direct US stocks, true US exposure is about {(us_direct + abroad) / le * 100:.1f}% of listed equity (direct alone: {us_direct / le * 100:.1f}%)."
    ]
    lines += [
        f"{a.split(' - ')[0]} and {b.split(' - ')[0]} hold the same companies for {c:.0f}% of each fund's weight."
        for a, b, c in pairs
        if c >= 10
    ]
    snap.lookthrough_lines = lines
    return notices
