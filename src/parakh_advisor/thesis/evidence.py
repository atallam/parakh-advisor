"""Evidence: the only facts the thesis agents may cite.

Each item has a stable id (`MET.<key>@<period>`), a value or quote, a date and a source. Agents
cite ids; code resolves them. An id that does not exist is rejected, which stops invented facts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from pydantic import BaseModel

from parakh_advisor.metrics.quality import CompanyMetrics


class Evidence(BaseModel):
    id: str
    kind: str  # metric | filing | news
    text: str
    value: float | None = None
    as_of: date
    source: str


def from_metrics(m: CompanyMetrics) -> list[Evidence]:
    """One evidence item per computed metric. N/A metrics are included so the agent sees the gap."""
    out: list[Evidence] = []
    as_of = m.quarter_end or m.fy_end
    if as_of is None:
        return out
    for x in m.metrics:
        period = (
            f"{(m.quarter_end or as_of):%Y%m}"
            if x.key in ("pe_ttm", "pe_vs_hist")
            else f"{(m.fy_end or as_of):%Y%m}"
        )
        text = (
            f"{x.label}: {x.value} {x.unit} ({x.basis})"
            if x.value is not None
            else f"{x.label}: n/a ({x.note})"
        )
        out.append(
            Evidence(
                id=f"MET.{x.key}@{period}",
                kind="metric",
                text=text,
                value=x.value,
                as_of=as_of,
                source="screener_export",
            )
        )
    return out


def digest(items: list[Evidence]) -> str:
    """Content hash of an evidence set; same inputs give the same digest (replay test)."""
    blob = json.dumps(sorted((e.id, e.text, str(e.as_of)) for e in items), separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def latest_by_indicator(items: list[Evidence]) -> dict[str, Evidence]:
    """`roe` -> its newest evidence item (ids look like MET.roe@202603)."""
    best: dict[str, Evidence] = {}
    for e in items:
        if not e.id.startswith("MET."):
            continue
        key = e.id[4:].split("@")[0]
        if key not in best or e.as_of >= best[key].as_of:
            best[key] = e
    return best
