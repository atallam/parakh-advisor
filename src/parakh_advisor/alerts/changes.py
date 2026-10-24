"""Change detection and the slow-upgrade rule (design 6.2 rule 4 and 6.4).

State per instrument is stored between runs in data/advice/state.json. Downgrades take effect at once.
An upgrade must be seen on two consecutive evaluations before it is reported, so risk is acted on
faster than optimism. Alerts always say what changed, the evidence ids, previous and new value, and
what would reverse it.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from parakh_advisor.thesis.models import Thesis

RANK = {"BROKEN": 0, "WEAKENING": 1, "INTACT": 2, "STRONG": 3}


class Alert(BaseModel):
    severity: str  # high | medium | low
    instrument_id: str
    symbol: str
    title: str
    detail: str
    evidence_ids: list[str] = []
    would_reverse: str = ""


class InstrumentState(BaseModel):
    stance: str | None = None
    pending_upgrade: str | None = None
    action: str | None = None
    thesis_version: int | None = None
    concentration_trim: bool = False
    far_over_cap: bool = False  # already alerted that it is >5 points over the cap
    drivers: dict[str, str] = {}
    kills: dict[str, bool] = {}


def load_state(path: str | Path) -> dict[str, InstrumentState]:
    p = Path(path)
    if not p.exists():
        return {}
    return {k: InstrumentState(**v) for k, v in json.loads(p.read_text(encoding="utf-8")).items()}


def save_state(path: str | Path, state: dict[str, InstrumentState]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({k: v.model_dump() for k, v in state.items()}, indent=2), encoding="utf-8"
    )


def effective_stance(prior: InstrumentState | None, new: str) -> tuple[str, str | None]:
    """Returns (stance to act on, pending upgrade). INSUFFICIENT passes through unchanged."""
    if prior is None or prior.stance is None or new not in RANK or prior.stance not in RANK:
        return new, None
    if RANK[new] < RANK[prior.stance]:
        return new, None  # downgrade: immediate
    if RANK[new] > RANK[prior.stance]:
        if prior.pending_upgrade == new:
            return new, None  # second consecutive evaluation: accept
        return prior.stance, new  # first sighting: hold the old stance, remember the candidate
    return new, None


def detect(
    symbol: str,
    iid: str,
    thesis: Thesis | None,
    prior: InstrumentState | None,
    stance: str | None,
    action: str | None,
    over_cap_pp: float = 0.0,
) -> list[Alert]:
    out: list[Alert] = []
    if thesis is None:
        return out
    ev = lambda *ids: sorted({i for d in ids for i in d})  # noqa: E731
    if prior is None or prior.thesis_version is None:
        out.append(
            Alert(
                severity="low",
                instrument_id=iid,
                symbol=symbol,
                title="New thesis created",
                detail=f"{symbol}: thesis v{thesis.version}, stance {stance}.",
                would_reverse="n/a",
            )
        )
        return out

    if (
        stance
        and prior.stance
        and stance != prior.stance
        and stance in RANK
        and prior.stance in RANK
    ):
        down = RANK[stance] < RANK[prior.stance]
        sev = "high" if stance == "BROKEN" else "medium" if down else "low"
        drv = [d for d in thesis.drivers if prior.drivers.get(d.id) != d.status.value]
        out.append(
            Alert(
                severity=sev,
                instrument_id=iid,
                symbol=symbol,
                title=f"Thesis {'downgraded' if down else 'upgraded'}: {prior.stance} to {stance}",
                detail="; ".join(
                    f"{d.id} {prior.drivers.get(d.id, '?')} to {d.status.value} ({d.statement[:70]})"
                    for d in drv
                )
                or "No single driver changed; see the thesis.",
                evidence_ids=ev(*[d.evidence_ids for d in drv]),
                would_reverse="The flagged driver recovering on two consecutive evaluations."
                if down
                else "A driver slipping back to WATCH.",
            )
        )
    for k in thesis.kill_criteria:
        if k.tripped and not prior.kills.get(k.id, False):
            out.append(
                Alert(
                    severity="high",
                    instrument_id=iid,
                    symbol=symbol,
                    title=f"Kill criterion {k.id} tripped",
                    detail=k.description,
                    would_reverse="The metric recovering past its threshold on a later filing, or your confirmation that the thesis still holds.",
                )
            )
    for d in thesis.drivers:
        was = prior.drivers.get(d.id)
        if (
            was
            and was != d.status.value
            and d.status.value in ("WATCH", "BROKEN")
            and not (stance and prior.stance and RANK.get(stance, 9) < RANK.get(prior.stance, 9))
        ):
            out.append(
                Alert(
                    severity="medium",
                    instrument_id=iid,
                    symbol=symbol,
                    title=f"Driver {d.id} moved {was} to {d.status.value}",
                    detail=d.statement[:140],
                    evidence_ids=d.evidence_ids,
                    would_reverse="The metric back inside its warn threshold.",
                )
            )
    if action and prior.action and action != prior.action:
        sev = "high" if action == "EXIT" else "medium"
        out.append(
            Alert(
                severity=sev,
                instrument_id=iid,
                symbol=symbol,
                title=f"Advice changed: {prior.action} to {action}",
                detail="See the reasons in the report.",
                would_reverse="See 'what would change this advice' in the report.",
            )
        )
    if over_cap_pp > 5 and not prior.far_over_cap:
        out.append(
            Alert(
                severity="high",
                instrument_id=iid,
                symbol=symbol,
                title="Position far above the cap",
                detail=f"{over_cap_pp:.1f} points above the single-name cap.",
                would_reverse="Price moves or trims bringing it back under the cap.",
            )
        )
    return out


def collapse_baseline(alerts: list[Alert], min_count: int = 4) -> list[Alert]:
    """On a first run every thesis is 'new'. Show one summary line instead of a wall of alerts."""
    import re

    new = [a for a in alerts if a.title == "New thesis created"]
    if len(new) < min_count:
        return alerts
    groups: dict[str, list[str]] = {}
    for a in new:
        m = re.search(r"stance (\w+)", a.detail)
        groups.setdefault(m.group(1) if m else "UNKNOWN", []).append(a.symbol)
    detail = "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(groups.items()))
    summary = Alert(
        severity="low",
        instrument_id="*",
        symbol="BASELINE",
        title=f"{len(new)} theses created (first run)",
        detail=detail,
        would_reverse="n/a",
    )
    return [a for a in alerts if a.title != "New thesis created"] + [summary]
