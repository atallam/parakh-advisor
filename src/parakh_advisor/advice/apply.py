"""Attach thesis-based advice to a snapshot, and produce alerts + the next run's state."""

from __future__ import annotations

from parakh_advisor.advice.matrix import BANDS, decide
from parakh_advisor.advice.policy import Policy
from parakh_advisor.advice.snapshot import RiskAction, Snapshot
from parakh_advisor.advice.valuation import valuation_stance
from parakh_advisor.alerts.changes import Alert, InstrumentState, detect, effective_stance
from parakh_advisor.contracts.holdings_v2 import DIRECT_STOCKS
from parakh_advisor.ingest.instruments import Instrument
from parakh_advisor.metrics.quality import CompanyMetrics
from parakh_advisor.thesis.models import Thesis

REASON_TEXT = {
    "CONCENTRATION": "The position is above your concentration limit. This is a risk-policy reason and holds whatever the thesis says.",
    "THESIS_BROKEN": "A kill criterion set when the thesis was written has tripped.",
    "THESIS_WEAKENING": "At least one driver of the thesis is past its warning line.",
    "NO_ADDS": "No additions while the thesis is weakening.",
    "VALUATION_RICH": "The share price looks rich against the stock's own history.",
    "ABOVE_BAND": "The position is above its conviction band.",
    "BELOW_BAND": "The position is below its conviction band.",
    "VALUATION_CHEAP": "Valuation looks cheap against its own history.",
    "VALUATION_FAIR": "Valuation looks fair against its own history.",
    "THESIS_INTACT": "The thesis and its drivers are holding up.",
    "DUST": "Too small to move the portfolio either way.",
    "NO_THESIS_YET": "No thesis yet for this company.",
    "VALUATION_NA": "There is no readable valuation (too little history, losses, or distorted earnings), so the system will not suggest adding.",
    "VALUATION_STRETCHED": "The share price looks stretched against the stock's own history.",
    "LOW_CONFIDENCE": "Size and valuation would support adding, but the thesis rests on reported numbers only (low confidence). Supply filings or call material first.",
    "INSUFFICIENT_EVIDENCE": "Too little history or evidence to test a thesis. The system does not pretend to know.",
}


def _lakh(inr: float) -> str:
    return f"\u20b9{inr / 100000:.1f} lakh"


def size_note(
    *,
    weight: float,
    value_inr: float,
    listed_equity_inr: float,
    action: RiskAction,
    reasons: list[str],
    conviction: str,
    cap: float,
    buffer: float,
) -> str:
    """Rupee size of the move the advice implies, before tax. Empty when no size is implied."""
    if action == RiskAction.TRIM and "CONCENTRATION" in reasons:
        to_cap = value_inr - cap / 100 * listed_equity_inr
        to_clear = value_inr - (cap - buffer) / 100 * listed_equity_inr
        return (
            f"About {_lakh(to_cap)} above the {cap:g}% cap; trimming about {_lakh(to_clear)} "
            f"gets it to {cap - buffer:g}%, below which this alert clears."
        )
    lo, hi = BANDS.get(conviction, BANDS["unset"])
    if conviction == "unset":
        return ""
    if action == RiskAction.TRIM and weight > hi:
        return f"About {_lakh(value_inr - hi / 100 * listed_equity_inr)} above the top of its {conviction} band ({hi:g}%)."
    if (
        conviction in ("core", "standard")
        and weight < lo
        and action
        in (
            RiskAction.ADD,
            RiskAction.REVIEW,
            RiskAction.HOLD,
        )
    ):
        gap = lo / 100 * listed_equity_inr - value_inr
        return f"About {_lakh(gap)} short of the bottom of its {conviction} band ({lo:g}%), if you chose to add."
    return ""


def apply_advice(
    snap: Snapshot,
    policy: Policy,
    theses: dict[str, Thesis],
    metrics: dict[str, CompanyMetrics],
    instruments: dict[str, Instrument],
    state: dict[str, InstrumentState],
) -> tuple[list[Alert], dict[str, InstrumentState]]:
    alerts: list[Alert] = []
    new_state: dict[str, InstrumentState] = dict(state)
    for h in snap.holdings:
        if h.asset_class not in DIRECT_STOCKS or h.weight_pct is None:
            continue
        inst = instruments.get(h.instrument_id)
        thesis = theses.get(h.instrument_id)
        prior = state.get(h.instrument_id)
        raw_stance = thesis.stance.value if thesis else None
        stance, pending = effective_stance(prior, raw_stance) if raw_stance else (None, None)
        val, basis = valuation_stance(
            metrics.get(h.instrument_id), inst.valuation_history_reliable if inst else True
        )
        conviction = inst.conviction if inst else "unset"
        adv = decide(
            weight=h.weight_pct,
            cap=policy.single_name_cap_pct,
            buffer=policy.hysteresis_buffer_pp,
            dust=policy.dust_pct,
            stance=stance,
            valuation=val,
            conviction=conviction,
            prior_trim_for_concentration=bool(prior and prior.concentration_trim),
            confidence=thesis.confidence.value if thesis else "LOW",
        )
        h.action = adv.action
        h.reason_codes = adv.reasons
        h.note = " ".join(REASON_TEXT.get(r, r) for r in adv.reasons)
        h.would_change = adv.would_change
        h.stance, h.valuation, h.valuation_basis, h.conviction = stance, val, basis, conviction
        if "CONCENTRATION" in adv.reasons:
            h.amount_over_cap_inr = max(
                0.0, h.value_inr - policy.single_name_cap_pct / 100 * snap.listed_equity_inr
            )
        h.size_note = size_note(
            weight=h.weight_pct,
            value_inr=h.value_inr,
            listed_equity_inr=snap.listed_equity_inr,
            action=adv.action,
            reasons=adv.reasons,
            conviction=conviction,
            cap=policy.single_name_cap_pct,
            buffer=policy.hysteresis_buffer_pp,
        )
        if thesis:
            h.thesis_status = f"v{thesis.version}, {thesis.confidence.value.lower()} confidence"
            h.thesis_version = thesis.version
            h.counter_case = thesis.skeptic_counter_case
            h.watch_drivers = [
                f"{d.id}: {d.statement[:90]}"
                for d in thesis.drivers
                if d.status.value in ("WATCH", "BROKEN")
            ]
        over_pp = max(0.0, h.weight_pct - policy.single_name_cap_pct)
        alerts += detect(
            h.symbol or h.name, h.instrument_id, thesis, prior, stance, adv.action.value, over_pp
        )
        new_state[h.instrument_id] = InstrumentState(
            stance=stance if stance else (prior.stance if prior else None),
            pending_upgrade=pending,
            action=adv.action.value,
            thesis_version=thesis.version if thesis else (prior.thesis_version if prior else None),
            concentration_trim=adv.action == RiskAction.TRIM and "CONCENTRATION" in adv.reasons,
            far_over_cap=over_pp > 5,
            drivers={d.id: d.status.value for d in thesis.drivers}
            if thesis
            else (prior.drivers if prior else {}),
            kills={k.id: k.tripped for k in thesis.kill_criteria}
            if thesis
            else (prior.kills if prior else {}),
        )
    order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: order[a.severity])
    snap.single_name_breaches = [
        h.symbol or h.name
        for h in snap.holdings
        if "CONCENTRATION" in h.reason_codes and h.asset_class in DIRECT_STOCKS
    ]
    return alerts, new_state
