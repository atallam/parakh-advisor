"""The decision matrix (design section 7.3). Pure function: same inputs, same label.

Precedence: dust, then a broken thesis, then the concentration cap (a risk-policy reason that holds
whatever the thesis says), then no/insufficient thesis, then the stance x valuation x band rules.
This is advice for the investor to weigh. It is never an instruction to trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from parakh_advisor.advice.snapshot import RiskAction

BANDS = {
    "unset": (0.0, 100.0),
    "core": (6.0, 10.0),
    "standard": (3.0, 6.0),
    "starter": (1.0, 3.0),
    "tracking": (0.0, 1.0),
}
RICH = {"RICH", "STRETCHED"}


@dataclass
class Advice:
    action: RiskAction
    reasons: list[str] = field(default_factory=list)
    would_change: str = ""


def decide(
    *,
    weight: float,
    cap: float,
    buffer: float,
    dust: float,
    stance: str | None,
    valuation: str,
    conviction: str = "unset",
    prior_trim_for_concentration: bool = False,
) -> Advice:
    lo, hi = BANDS.get(conviction, BANDS["unset"])
    weak_reason = ["THESIS_WEAKENING"] if stance == "WEAKENING" else []

    if weight < dust:
        return Advice(
            RiskAction.BUILD_OR_CONSOLIDATE,
            ["DUST"],
            "Add enough to matter, or fold this into a position you believe in.",
        )

    if stance == "BROKEN":
        reasons = ["THESIS_BROKEN"] + (["CONCENTRATION"] if weight > cap else [])
        return Advice(
            RiskAction.EXIT,
            reasons,
            "A tripped kill criterion stays tripped until the metric recovers on a later filing, or you confirm the thesis still holds.",
        )

    over = weight > cap or (prior_trim_for_concentration and weight > cap - buffer)
    if over:
        return Advice(
            RiskAction.TRIM,
            ["CONCENTRATION"] + weak_reason + (["VALUATION_RICH"] if valuation in RICH else []),
            f"Falling below {cap - buffer:g}% of listed equity (cap {cap:g}% less a {buffer:g}-point buffer), by price moves or by trimming.",
        )

    if stance is None:
        return Advice(
            RiskAction.REVIEW,
            ["NO_THESIS_YET"],
            "A thesis for this company (needs fundamentals loaded).",
        )
    if stance == "INSUFFICIENT":
        return Advice(
            RiskAction.REVIEW,
            ["INSUFFICIENT_EVIDENCE"],
            "More reported history or supplied documents, so the thesis can be tested.",
        )

    if stance == "WEAKENING":
        if valuation in RICH:
            return Advice(
                RiskAction.TRIM,
                ["THESIS_WEAKENING", "VALUATION_RICH"],
                "The weakest driver returns to OK on two consecutive evaluations, or the valuation falls back to FAIR.",
            )
        return Advice(
            RiskAction.HOLD,
            ["THESIS_WEAKENING", "NO_ADDS"],
            "The weakest driver returns to OK on two consecutive evaluations.",
        )

    # INTACT or STRONG
    if valuation in RICH and weight > hi:
        return Advice(
            RiskAction.TRIM,
            ["VALUATION_RICH", "ABOVE_BAND"],
            f"Valuation easing to FAIR, or the position sitting within its {conviction} band (up to {hi:g}%).",
        )
    if valuation in {"CHEAP", "FAIR"} and weight < lo and conviction in {"core", "standard"}:
        return Advice(
            RiskAction.ADD,
            ["BELOW_BAND", f"VALUATION_{valuation}"],
            "The thesis weakening, valuation turning RICH, or the position reaching the bottom of its band.",
        )
    return Advice(
        RiskAction.HOLD,
        ["THESIS_INTACT"] if stance in {"INTACT", "STRONG"} else [],
        "A driver moving to WATCH, a kill criterion tripping, or the valuation turning RICH while above its band.",
    )
