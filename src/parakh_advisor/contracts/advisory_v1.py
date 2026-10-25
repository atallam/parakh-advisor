"""Output contract `advisory.v1`: what Parakh hands to WealthLens (design 9.3).

Pure functions build row models from a finished run; nothing here touches the network. Rows are
append-only. Every id is derived from content (uuid5), so publishing the same run twice writes the
same ids and the second write is ignored. WealthLens owns `user_id`; Parakh only stamps it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime

from pydantic import BaseModel, Field

from parakh_advisor.advice.matrix import BANDS
from parakh_advisor.advice.policy import Policy
from parakh_advisor.advice.snapshot import Snapshot
from parakh_advisor.alerts.changes import Alert
from parakh_advisor.metrics.quality import CompanyMetrics
from parakh_advisor.thesis.evidence import from_metrics, latest_by_indicator
from parakh_advisor.thesis.models import Thesis

CONTRACT = "advisory.v1"
NAMESPACE = uuid.UUID("6f0a1c0e-5b7d-4f43-9a52-2f8f0d1b7a10")  # fixed: ids must be stable forever

# insert order; `advisory_runs` goes last as the commit marker (a run row means the rest landed)
TABLES = [
    "advisory_theses",
    "advisory_drivers",
    "advisory_actions",
    "advisory_alerts",
    "advisory_evidence",
    "advisory_portfolio",
    "advisory_runs",
]
CONFLICT = {
    "advisory_theses": "id",
    "advisory_drivers": "thesis_id,driver_id",
    "advisory_actions": "id",
    "advisory_alerts": "id",
    "advisory_evidence": "id",
    "advisory_portfolio": "run_id",
    "advisory_runs": "id",
}


def _id(*parts: object) -> str:
    return str(uuid.uuid5(NAMESPACE, "|".join(str(p) for p in parts)))


class Run(BaseModel):
    id: str
    user_id: str
    kind: str  # advise
    started_at: datetime
    finished_at: datetime
    model: str | None
    policy_version: int
    status: str = "complete"
    contract: str = CONTRACT


class ThesisRow(BaseModel):
    id: str
    user_id: str
    instrument_id: str
    symbol: str | None
    version: int
    created_at: datetime
    stance: str
    confidence: str
    valuation_stance: str | None
    change_decision: str
    body: dict
    inputs_digest: str


class DriverRow(BaseModel):
    thesis_id: str
    user_id: str
    driver_id: str
    kind: str
    indicator: str | None
    status: str
    value: float | None
    evidence_ids: list[str]


class ActionRow(BaseModel):
    id: str
    user_id: str
    instrument_id: str
    symbol: str | None
    run_id: str
    action: str
    reason_codes: list[str]
    weight_pct: float | None
    band_low: float | None
    band_high: float | None
    what_would_change: str
    created_at: datetime


class AlertRow(BaseModel):
    id: str
    user_id: str
    instrument_id: str
    run_id: str
    severity: str
    kind: str
    title: str
    prev_value: str | None
    new_value: str | None
    detail: str
    evidence_ids: list[str]
    created_at: datetime
    acknowledged_at: datetime | None = None


class PortfolioRow(BaseModel):
    run_id: str
    user_id: str
    snapshot: dict


class Bundle(BaseModel):
    contract: str = CONTRACT
    advisory_theses: list[ThesisRow] = Field(default_factory=list)
    advisory_drivers: list[DriverRow] = Field(default_factory=list)
    advisory_actions: list[ActionRow] = Field(default_factory=list)
    advisory_alerts: list[AlertRow] = Field(default_factory=list)
    advisory_evidence: list[dict] = Field(
        default_factory=list
    )  # reserved: filled in a later version
    advisory_portfolio: list[PortfolioRow] = Field(default_factory=list)
    advisory_runs: list[Run] = Field(default_factory=list)

    def rows(self, table: str) -> list[dict]:
        return [
            r.model_dump(mode="json") if isinstance(r, BaseModel) else r
            for r in getattr(self, table)
        ]


def _day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def build_bundle(
    snap: Snapshot,
    alerts: list[Alert],
    theses: dict[str, Thesis],
    metrics: dict[str, CompanyMetrics],
    policy: Policy,
    user_id: str,
    symbols: dict[str, str | None] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> Bundle:
    """Rows for one run. `created_at` of derived rows is the data date, not the wall clock, so the
    same inputs give the same bytes and re-publishing is a no-op."""
    symbols = symbols or {}
    held = {h.instrument_id: h for h in snap.holdings}
    ref = _day_start(snap.reference_date)
    bundle = Bundle()

    for iid, t in sorted(theses.items()):
        tid = _id(user_id, iid, "thesis", t.version)
        h = held.get(iid)
        bundle.advisory_theses.append(
            ThesisRow(
                id=tid,
                user_id=user_id,
                instrument_id=iid,
                symbol=symbols.get(iid) or (h.symbol if h else None),
                version=t.version,
                created_at=_day_start(t.as_of_data_date),
                stance=t.stance.value,
                confidence=t.confidence.value,
                valuation_stance=h.valuation if h else None,
                change_decision=t.change_decision.value,
                body=t.model_dump(mode="json"),
                inputs_digest=t.inputs_digest,
            )
        )
        ev = latest_by_indicator(from_metrics(metrics[iid])) if iid in metrics else {}
        for d in t.drivers:
            e = ev.get(d.indicator or "")
            bundle.advisory_drivers.append(
                DriverRow(
                    thesis_id=tid,
                    user_id=user_id,
                    driver_id=d.id,
                    kind=d.kind,
                    indicator=d.indicator,
                    status=d.status.value,
                    value=e.value if e else None,
                    evidence_ids=list(d.evidence_ids),
                )
            )

    # the run id depends on what the run says, not when it ran
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "ref": str(snap.reference_date),
                "theses": sorted(t.inputs_digest + str(t.version) for t in theses.values()),
                "actions": sorted(
                    f"{h.instrument_id}:{h.action.value if h.action else '-'}:{h.valuation}:{h.stance}"
                    for h in snap.holdings
                ),
                "alerts": sorted(f"{a.instrument_id}:{a.title}" for a in alerts),
                "policy": policy.version,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    run_id = _id(user_id, "run", fingerprint)

    for h in snap.holdings:
        if h.action is None:
            continue
        lo, hi = BANDS.get(h.conviction, BANDS["unset"])
        bundle.advisory_actions.append(
            ActionRow(
                id=_id(run_id, h.instrument_id),
                user_id=user_id,
                instrument_id=h.instrument_id,
                symbol=h.symbol,
                run_id=run_id,
                action=h.action.value,
                reason_codes=list(h.reason_codes),
                weight_pct=None if h.weight_pct is None else round(h.weight_pct, 4),
                band_low=lo,
                band_high=hi,
                what_would_change=h.would_change,
                created_at=ref,
            )
        )
    for a in alerts:
        bundle.advisory_alerts.append(
            AlertRow(
                id=_id(run_id, a.instrument_id, a.title),
                user_id=user_id,
                instrument_id=a.instrument_id,
                run_id=run_id,
                severity=a.severity,
                kind=a.title,
                title=a.title,
                prev_value=None,
                new_value=None,
                detail=a.detail,
                evidence_ids=list(a.evidence_ids),
                created_at=ref,
            )
        )
    bundle.advisory_portfolio.append(
        PortfolioRow(run_id=run_id, user_id=user_id, snapshot=snap.model_dump(mode="json"))
    )
    now = datetime.now(UTC)
    bundle.advisory_runs.append(
        Run(
            id=run_id,
            user_id=user_id,
            kind="advise",
            started_at=started_at or now,
            finished_at=finished_at or now,
            model=next((t.model for t in theses.values()), None),
            policy_version=policy.version,
        )
    )
    return bundle
