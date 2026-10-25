"""Portfolio snapshot: allocation, concentration, dust, data health.

Day 1 produces the *risk* view only. Thesis-based advice arrives with the thesis engine, so
every position carries `thesis_status = "none yet"` and a risk-derived action (or REVIEW).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

from parakh_advisor.advice.policy import Policy
from parakh_advisor.contracts.holdings_v2 import (
    CONTEXT_ASSETS,
    DIRECT_STOCKS,
    AssetClass,
    DQFlag,
    Portfolio,
    Position,
    Severity,
)


class RiskAction(StrEnum):
    TRIM = "TRIM"  # above the single-name cap
    BUILD_OR_CONSOLIDATE = "BUILD OR CONSOLIDATE"  # too small to matter
    REVIEW = "REVIEW"  # no thesis yet / fund review pending
    ADD = "ADD"
    HOLD = "HOLD"
    EXIT = "EXIT"  # "consider exiting": thesis broken


class Holding(BaseModel):
    """One instrument, merged across members."""

    instrument_id: str
    name: str
    symbol: str | None
    asset_class: AssetClass
    exchange: str | None
    member_ids: list[str]
    units: float
    value_inr: float
    weight_pct: float | None  # of listed equity; None for non-equity
    cost_value_inr: float | None
    pnl_pct: float | None
    position_as_of: date | None
    action: RiskAction | None
    reason_codes: list[str] = Field(default_factory=list)
    note: str = ""
    amount_over_cap_inr: float | None = None
    size_note: str = ""
    flag_codes: list[str] = Field(default_factory=list)
    thesis_status: str = "none yet"
    stance: str | None = None
    valuation: str | None = None
    valuation_basis: str = ""
    conviction: str = "unset"
    would_change: str = ""
    counter_case: str | None = None
    thesis_version: int | None = None
    watch_drivers: list[str] = Field(default_factory=list)
    scheme_code: str | None = None
    category: str | None = None
    plan: str | None = None
    fund_status: str | None = None
    fund_lines: list[str] = Field(default_factory=list)


class AllocationRow(BaseModel):
    asset_class: str
    value_inr: float
    pct_of_net_worth: float


class Snapshot(BaseModel):
    reference_date: date
    member_filter: str | None
    net_worth_inr: float
    listed_equity_inr: float
    allocation: list[AllocationRow]
    equity_split_pct: dict[str, float]  # us_direct / india_direct / funds / etf
    holdings: list[Holding]
    top3_names: list[str]
    top3_pct: float
    top3_breach: bool
    single_name_breaches: list[str]
    dust: list[str]
    flags: list[DQFlag]
    cost_pending_count: int
    cost_tracked_count: int
    oldest_position_as_of: date | None
    newest_position_as_of: date | None
    policy_single_cap: float
    policy_top3_cap: float
    policy_dust_pct: float
    verdict: list[str]
    fund_overlap: list[str] = Field(default_factory=list)
    lookthrough_rows: list[dict] = Field(default_factory=list)
    lookthrough_lines: list[str] = Field(default_factory=list)
    acknowledged_flags: list[str] = Field(
        default_factory=list
    )  # data-quality flags you have confirmed


def _merge(positions: list[Position]) -> dict[str, list[Position]]:
    groups: dict[str, list[Position]] = defaultdict(list)
    for p in positions:
        groups[p.instrument_id].append(p)
    return groups


def _holding(group: list[Position], listed_total: float, policy: Policy) -> Holding:
    first = group[0]
    value = sum(p.value_inr or 0.0 for p in group)
    costs = [p.cost_value_inr for p in group]
    cost_known = all(c is not None for c in costs)
    cost_total = sum(c for c in costs if c is not None) if cost_known else None
    pnl = (
        (value / cost_total - 1) * 100
        if cost_total and first.asset_class != AssetClass.CASH
        else None
    )
    in_equity = first.is_listed_equity and listed_total > 0
    weight = (value / listed_total * 100) if in_equity else None
    dates = [p.position_as_of for p in group if p.position_as_of]

    action: RiskAction | None = None
    reasons: list[str] = []
    note = ""
    over: float | None = None
    if first.asset_class in DIRECT_STOCKS and weight is not None:
        if weight > policy.single_name_cap_pct:
            action = RiskAction.TRIM
            over = max(0.0, value - policy.single_name_cap_pct / 100 * listed_total)
            reasons.append("CONCENTRATION")
            note = (
                f"{weight:.1f}% of listed equity vs {policy.single_name_cap_pct:g}% cap. "
                f"About ₹{over / 1e5:.1f} lakh above the cap at today's portfolio size. "
                "A risk-policy view, independent of the company thesis."
            )
        elif weight < policy.dust_pct:
            action = RiskAction.BUILD_OR_CONSOLIDATE
            reasons.append("DUST")
            note = f"{weight:.2f}% of listed equity: too small to move the portfolio either way."
        else:
            action = RiskAction.REVIEW
            reasons.append("NO_THESIS_YET")
            note = "Within policy. A company thesis is needed before any add/hold/trim/exit view."
    elif first.asset_class in (AssetClass.FUND, AssetClass.ETF) and first.sleeve == "equity":
        action = RiskAction.REVIEW
        reasons.append("FUND_REVIEW_PENDING")
        note = "Fund health card and overlap check come with the fund module."

    return Holding(
        scheme_code=first.scheme_code,
        category=first.category,
        plan=first.plan,
        instrument_id=first.instrument_id,
        name=first.name,
        symbol=first.symbol,
        asset_class=first.asset_class,
        exchange=first.exchange,
        member_ids=sorted({p.member_id for p in group}),
        units=sum(p.units for p in group),
        value_inr=value,
        weight_pct=weight,
        cost_value_inr=cost_total,
        pnl_pct=pnl,
        position_as_of=min(dates) if dates else None,
        action=action,
        reason_codes=reasons,
        note=note,
        amount_over_cap_inr=over,
    )


def build_snapshot(
    portfolio: Portfolio,
    policy: Policy,
    member: str | None = None,
    acknowledged: dict[str, set[str]] | None = None,
) -> Snapshot:
    """`acknowledged` maps instrument_id -> data-quality codes you have confirmed (set `acknowledge:` in
    config/instruments.yaml). They are removed from the flags and listed once as acknowledged."""
    positions = [p for p in portfolio.positions if member is None or p.member_id == member]
    if not positions:
        raise ValueError(f"No positions found for member filter {member!r}.")

    net_worth = sum(p.value_inr or 0.0 for p in positions)
    listed_total = sum((p.value_inr or 0.0) for p in positions if p.is_listed_equity)

    alloc: dict[str, float] = defaultdict(float)
    for p in positions:
        label = (
            "COMMODITY ETF"
            if (p.asset_class == AssetClass.ETF and p.sleeve == "commodity")
            else p.asset_class.value
        )
        alloc[label] += p.value_inr or 0.0
    allocation = [
        AllocationRow(
            asset_class=k, value_inr=v, pct_of_net_worth=(v / net_worth * 100) if net_worth else 0.0
        )
        for k, v in sorted(alloc.items(), key=lambda kv: -kv[1])
    ]

    def share(pred) -> float:
        v = sum((p.value_inr or 0.0) for p in positions if p.is_listed_equity and pred(p))
        return v / listed_total * 100 if listed_total else 0.0

    equity_split = {
        "US direct stocks": share(lambda p: p.asset_class == AssetClass.US_EQUITY),
        "India direct stocks": share(lambda p: p.asset_class == AssetClass.IN_EQUITY),
        "Mutual funds & equity ETFs": share(
            lambda p: p.asset_class in (AssetClass.FUND, AssetClass.ETF)
        ),
    }

    holdings = [_holding(g, listed_total, policy) for g in _merge(positions).values()]
    holdings.sort(key=lambda h: -h.value_inr)

    direct = [h for h in holdings if h.asset_class in DIRECT_STOCKS and h.weight_pct is not None]
    top3 = sorted(direct, key=lambda h: -h.weight_pct)[:3]
    top3_pct = sum(h.weight_pct for h in top3)
    breaches = [h.symbol or h.name for h in direct if h.action == RiskAction.TRIM]
    dust = [h.symbol or h.name for h in direct if h.action == RiskAction.BUILD_OR_CONSOLIDATE]

    ids = {h.instrument_id for h in holdings}
    flags = [f for f in portfolio.flags if f.instrument_id is None or f.instrument_id in ids]
    acked = acknowledged or {}
    shown = [f for f in flags if f.code not in acked.get(f.instrument_id or "", set())]
    names = {h.instrument_id: (h.symbol or h.name) for h in holdings}
    acknowledged_flags = sorted(
        {f"{names.get(f.instrument_id, f.instrument_id)} {f.code}" for f in flags if f not in shown}
    )
    flags = shown
    for h in holdings:
        h.flag_codes = sorted({f.code for f in flags if f.instrument_id == h.instrument_id})

    needs_cost = [h for h in holdings if h.asset_class not in CONTEXT_ASSETS]
    pending = sum(1 for h in needs_cost if h.cost_value_inr is None)
    dates = [h.position_as_of for h in needs_cost if h.position_as_of]

    snap = Snapshot(
        reference_date=portfolio.reference_date,
        member_filter=member,
        net_worth_inr=net_worth,
        listed_equity_inr=listed_total,
        allocation=allocation,
        equity_split_pct=equity_split,
        holdings=holdings,
        top3_names=[h.symbol or h.name for h in top3],
        top3_pct=top3_pct,
        top3_breach=top3_pct > policy.top3_cap_pct,
        single_name_breaches=breaches,
        dust=dust,
        flags=flags,
        acknowledged_flags=acknowledged_flags,
        cost_pending_count=pending,
        cost_tracked_count=len(needs_cost) - pending,
        oldest_position_as_of=min(dates) if dates else None,
        newest_position_as_of=max(dates) if dates else None,
        policy_single_cap=policy.single_name_cap_pct,
        policy_top3_cap=policy.top3_cap_pct,
        policy_dust_pct=policy.dust_pct,
        verdict=[],
    )
    snap.verdict = _verdict(snap)
    return snap


def _verdict(s: Snapshot) -> list[str]:
    """Three plain-language lines, generated from numbers (never from an LLM)."""
    lines: list[str] = []
    if s.top3_breach or s.single_name_breaches:
        names = ", ".join(s.top3_names)
        part = f"Concentration is the main issue: {names} are {s.top3_pct:.0f}% of listed equity (cap {s.policy_top3_cap:g}%)."
        if s.single_name_breaches:
            part += f" {len(s.single_name_breaches)} name(s) are above the {s.policy_single_cap:g}% single-name cap."
        lines.append(part)
    else:
        lines.append(
            f"Concentration is within policy: the top 3 names are {s.top3_pct:.0f}% of listed equity."
        )
    us = s.equity_split_pct.get("US direct stocks", 0.0)
    ind = s.equity_split_pct.get("India direct stocks", 0.0)
    fund = s.equity_split_pct.get("Mutual funds & equity ETFs", 0.0)
    lines.append(
        f"Listed equity is {us:.0f}% US stocks, {ind:.0f}% Indian stocks and {fund:.0f}% funds."
    )
    tail = []
    if s.dust:
        tail.append(f"{len(s.dust)} position(s) are too small to matter ({', '.join(s.dust)}).")
    tail.append(
        f"Cost basis is pending for {s.cost_pending_count} of {s.cost_pending_count + s.cost_tracked_count} positions."
    )
    lines.append(" ".join(tail))
    return lines


def warn_flags(s: Snapshot) -> list[DQFlag]:
    return [f for f in s.flags if f.severity == Severity.WARN]
