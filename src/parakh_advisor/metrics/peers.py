"""Where a company sits among its peers, as percentiles (0 to 100, higher is better).

A cohort is a named peer group from config/peers.yaml. Each peer is run through the same metric code
as the holding, so the numbers are comparable. Percentiles are shown with the cohort name and size;
fewer than MIN_PEERS usable peers gives no percentile rather than a noisy one. The holding itself is
never part of its own cohort.

Quality score = average percentile over growth, return on capital, margin, leverage (lower is
better) and cash conversion; banks use growth, profit growth and ROE. A score of 66.7 or more is the
top third and can lift an INTACT thesis to STRONG (design 6.3). The P/E percentile is information
only (high = dearer than most peers); it does not move any label.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from parakh_advisor.metrics.quality import CompanyMetrics
from parakh_advisor.thesis.evidence import Evidence

MIN_PEERS = 5
MIN_DIMS = 3
TOP_THIRD = 200 / 3

# (metric key, higher is better)
DIMS_STANDARD = [
    ("rev_cagr_3", True),
    ("roce", True),
    ("op_margin", True),
    ("debt_equity", False),
    ("cfo_np", True),
]
DIMS_BANK = [("rev_cagr_3", True), ("np_cagr_3", True), ("roe", True)]


class SectorContext(BaseModel):
    group: str
    peers: int  # usable peers (the holding excluded)
    quality_pct: float | None = None
    dims: dict[str, float] = {}
    pe_pct: float | None = None
    note: str | None = None  # why there is no percentile

    @property
    def top_third(self) -> bool:
        return self.quality_pct is not None and self.quality_pct >= TOP_THIRD


def rank(value: float, others: list[float], higher_is_better: bool = True) -> float:
    """Share of the others that the value beats, ties counting half. 0 to 100."""
    if not others:
        raise ValueError("rank needs at least one other value")
    wins = sum((value > o) if higher_is_better else (value < o) for o in others)
    ties = sum(value == o for o in others)
    return 100 * (wins + 0.5 * ties) / len(others)


def _vals(ms: list[CompanyMetrics], key: str) -> list[float]:
    out = []
    for m in ms:
        x = m.get(key)
        if x is not None and x.value is not None:
            out.append(x.value)
    return out


def sector_context(
    group: str, subject: CompanyMetrics, peers: list[CompanyMetrics], profile: str = "standard"
) -> SectorContext:
    n = len(peers)
    if n < MIN_PEERS:
        return SectorContext(
            group=group,
            peers=n,
            note=f"only {n} usable peers in '{group}'; at least {MIN_PEERS} are needed for a percentile",
        )
    dims: dict[str, float] = {}
    for key, high in DIMS_BANK if profile == "bank" else DIMS_STANDARD:
        mine = subject.get(key)
        others = _vals(peers, key)
        if mine is None or mine.value is None or len(others) < MIN_PEERS:
            continue
        dims[key] = round(rank(mine.value, others, high), 1)
    pe = subject.get("pe_ttm")
    pe_others = _vals(peers, "pe_ttm")
    pe_pct = (
        round(100 - rank(pe.value, pe_others, False), 1)
        if pe is not None and pe.value is not None and len(pe_others) >= MIN_PEERS
        else None
    )
    if len(dims) < MIN_DIMS:
        return SectorContext(
            group=group,
            peers=n,
            dims=dims,
            pe_pct=pe_pct,
            note=f"only {len(dims)} of the quality measures could be ranked (need {MIN_DIMS})",
        )
    return SectorContext(
        group=group,
        peers=n,
        quality_pct=round(sum(dims.values()) / len(dims), 1),
        dims=dims,
        pe_pct=pe_pct,
    )


def to_evidence(ctx: SectorContext, as_of: date) -> list[Evidence]:
    """Evidence the thesis agents may cite. Missing percentiles are stated, not hidden."""
    period = f"{as_of:%Y%m}"
    where = f"cohort '{ctx.group}', {ctx.peers} peers"
    out: list[Evidence] = []
    if ctx.quality_pct is not None:
        detail = ", ".join(f"{k} {v:.0f}" for k, v in ctx.dims.items())
        out.append(
            Evidence(
                id=f"MET.sector_quality_pct@{period}",
                kind="metric",
                text=f"Sector quality percentile: {ctx.quality_pct:.0f} of 100 ({where}; {detail}). "
                "100 is best in the cohort.",
                value=ctx.quality_pct,
                as_of=as_of,
                source="peer_cohort",
            )
        )
    else:
        out.append(
            Evidence(
                id=f"MET.sector_quality_pct@{period}",
                kind="metric",
                text=f"Sector quality percentile: n/a ({ctx.note})",
                value=None,
                as_of=as_of,
                source="peer_cohort",
            )
        )
    if ctx.pe_pct is not None:
        out.append(
            Evidence(
                id=f"MET.sector_pe_pct@{period}",
                kind="metric",
                text=f"Trailing P/E percentile: {ctx.pe_pct:.0f} of 100 ({where}). 100 means dearer "
                "than every peer. Information only.",
                value=ctx.pe_pct,
                as_of=as_of,
                source="peer_cohort",
            )
        )
    return out
