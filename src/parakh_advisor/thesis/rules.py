"""Deterministic thesis rules: statuses, kill criteria, stance, and change validation.

Nothing here calls an LLM. The agent proposes; these rules decide what is accepted.
"""

from __future__ import annotations

import re

from parakh_advisor.thesis.evidence import Evidence, latest_by_indicator
from parakh_advisor.thesis.models import (
    Change,
    ChangeDecision,
    Confidence,
    Driver,
    DriverStatus,
    KillCriterion,
    Stance,
    Thesis,
)


def driver_status(d: Driver, ev: dict[str, Evidence]) -> DriverStatus:
    """Metric drivers are scored by thresholds. Qualitative drivers stay as set (UNKNOWN or OK/WATCH
    from a quoted source); the code never invents a verdict for them."""
    if d.kind != "metric":
        return d.status
    e = ev.get(d.indicator or "")
    if e is None or e.value is None or d.direction is None:
        return DriverStatus.UNKNOWN
    v = e.value
    good_high = d.direction == "gte"
    if d.break_threshold is not None and (
        v < d.break_threshold if good_high else v > d.break_threshold
    ):
        return DriverStatus.BROKEN
    if d.warn_threshold is not None and (
        v < d.warn_threshold if good_high else v > d.warn_threshold
    ):
        return DriverStatus.WATCH
    return DriverStatus.OK


def kill_tripped(k: KillCriterion, ev: dict[str, Evidence]) -> bool:
    e = ev.get(k.indicator)
    if e is None or e.value is None:
        return False  # cannot trip without a number; never guess
    return e.value < k.threshold if k.op == "<" else e.value > k.threshold


def evaluate(drivers: list[Driver], kills: list[KillCriterion], evidence: list[Evidence]):
    ev = latest_by_indicator(evidence)
    return (
        [d.model_copy(update={"status": driver_status(d, ev)}) for d in drivers],
        [k.model_copy(update={"tripped": kill_tripped(k, ev)}) for k in kills],
    )


def derive_stance(
    drivers: list[Driver],
    kills: list[KillCriterion],
    reported_quarters: int,
    top_third: bool = False,
    sourced: bool = False,
    no_earnings_record: bool = False,
) -> tuple[Stance, Confidence]:
    """Design section 6.3. `top_third` comes from sector percentiles (Day 4+).
    `no_earnings_record`: loss-making now and fewer than 2 profitable years, so a profit thesis cannot be tested.
    `sourced` is True only when some evidence comes from a filing or quoted source; a thesis built
    on computed numbers alone has confidence LOW, whatever the stance."""

    def cap(c: Confidence) -> Confidence:
        return c if sourced else Confidence.LOW

    measurable = [d for d in drivers if d.status != DriverStatus.UNKNOWN]
    if any(k.tripped for k in kills):
        return Stance.BROKEN, Confidence.HIGH
    if len(measurable) < 2 or reported_quarters < 8 or no_earnings_record:
        return Stance.INSUFFICIENT, Confidence.LOW
    # Any driver already past its warn line means the reason to own is not fully intact.
    if any(d.status in (DriverStatus.BROKEN, DriverStatus.WATCH) for d in drivers):
        return Stance.WEAKENING, cap(Confidence.MEDIUM)
    if sum(d.status == DriverStatus.OK for d in drivers) * 2 >= len(drivers):
        if top_third:
            return Stance.STRONG, cap(Confidence.MEDIUM)
        return Stance.INTACT, cap(Confidence.MEDIUM)
    return Stance.WEAKENING, Confidence.LOW


def validate_change(
    prior: Thesis, decision: ChangeDecision, changes: list[Change], evidence: list[Evidence]
) -> tuple[ChangeDecision, list[Change], list[str]]:
    """Burden of proof (6.2 rule 2). Every change must cite evidence that exists and is dated after
    the prior version. Changes failing that are dropped and logged; if none survive, REAFFIRM."""
    if decision in (ChangeDecision.REAFFIRM, ChangeDecision.NEW):
        return decision, [], []
    by_id = {e.id: e for e in evidence}
    kept: list[Change] = []
    rejected: list[str] = []
    for c in changes:
        cited = [by_id.get(i) for i in c.new_evidence_ids]
        if not cited or any(e is None for e in cited):
            rejected.append(f"{c.field}: cites missing or unknown evidence {c.new_evidence_ids}")
        elif not any(e.as_of > prior.as_of_data_date for e in cited if e):
            rejected.append(
                f"{c.field}: no cited evidence is newer than version {prior.version} ({prior.as_of_data_date})"
            )
        else:
            kept.append(c)
    return (decision if kept else ChangeDecision.REAFFIRM), kept, rejected


def apply_flags(
    drivers: list[Driver], flags: list[dict], evidence: list[Evidence]
) -> tuple[list[Driver], list[str]]:
    """Qualitative drivers may be moved to WATCH, and only with a quote that literally appears in a
    cited document passage. Anything else (BROKEN, OK, a missing quote, a paraphrase) is refused and
    logged. BROKEN comes only from a tripped kill criterion or the user's confirmation."""
    by_id = {e.id: e for e in evidence}
    by_driver = {d.id: d for d in drivers}
    rejected: list[str] = []
    out = {d.id: d for d in drivers}
    norm = lambda s: " ".join(str(s).lower().split())  # noqa: E731
    for f in flags:
        d = by_driver.get(str(f.get("driver_id")))
        if d is None or d.kind != "qualitative":
            rejected.append(f"flag on {f.get('driver_id')}: not a qualitative driver")
        elif str(f.get("status")).upper() != "WATCH":
            rejected.append(
                f"flag on {d.id}: only WATCH may be set by the model, got {f.get('status')}"
            )
        else:
            cited = [
                by_id[i]
                for i in f.get("evidence_ids", [])
                if i in by_id and by_id[i].kind != "metric"
            ]
            quote = norm(f.get("quote", ""))
            if len(quote) < 20 or not any(quote in norm(e.text) for e in cited):
                rejected.append(f"flag on {d.id}: quote not found verbatim in the cited passage")
            else:
                out[d.id] = d.model_copy(
                    update={
                        "status": DriverStatus.WATCH,
                        "evidence_ids": sorted(set(d.evidence_ids) | {e.id for e in cited}),
                    }
                )
    return [out[d.id] for d in drivers], rejected


def hygiene_drivers(
    drivers: list[Driver], evidence: list[Evidence], profile: str = "standard"
) -> list[Driver]:
    """Drivers that code adds when a known red flag is present at creation, so the first thesis does
    not depend on which drivers the model happened to pick. Skipped if a driver already monitors the
    indicator. Only a warn line is set: they raise WATCH, never BROKEN."""
    ev = latest_by_indicator(evidence)
    have = {d.indicator for d in drivers if d.indicator}

    def val(k: str) -> float | None:
        e = ev.get(k)
        return None if e is None else e.value

    checks = [
        (
            "cfo_np",
            "gte",
            0.5,
            "Cash conversion: operating cash flow should cover at least half of reported profit.",
            profile != "broker"
            and (val("np_fy") or 0) > 0
            and val("cfo_np") is not None
            and val("cfo_np") < 0.5,
        ),
        (
            "int_cover",
            "gte",
            1.5,
            "Interest cover should stay above 1.5x.",
            profile != "bank" and val("int_cover") is not None and val("int_cover") < 1.5,
        ),
        (
            "np_ttm",
            "gte",
            0.0,
            "Trailing four-quarter net profit should not be negative.",
            val("np_ttm") is not None and val("np_ttm") < 0,
        ),
        (
            "pe_vs_hist",
            "lte",
            30.0,
            "Trailing P/E should not sit more than 30% above its own 5-year median.",
            val("pe_vs_hist") is not None and val("pe_vs_hist") > 30,
        ),
        (
            "roe",
            "gte",
            10.0,
            "Return on equity should stay above 10%.",
            val("roe") is not None and val("roe") < 10,
        ),
        (
            "pe_ttm",
            "lte",
            60.0,
            "Trailing P/E should stay below 60x, or the price needs years of flawless growth.",
            val("pe_ttm") is not None and val("pe_ttm") > 60,
        ),
    ]
    out: list[Driver] = []
    n = 0
    for key, direction, warn, text, adverse in checks:
        if adverse and key not in have:
            n += 1
            e = ev[key]
            out.append(
                Driver(
                    id=f"H{n}",
                    statement=f"{text} (added by code: currently {e.value}.)",
                    kind="metric",
                    indicator=key,
                    direction=direction,
                    warn_threshold=warn,
                    break_threshold=None,
                    evidence_ids=[e.id],
                )
            )
    return out


MAX_WARN_GAP = 0.30  # a warn line may sit at most 30% of today's value away on the adverse side


def tighten_drivers(drivers: list[Driver], evidence: list[Evidence]) -> list[Driver]:
    """Models set warn lines far from today's value (the Skeptic keeps flagging this). At creation,
    code pulls any warn line that is more than MAX_WARN_GAP away to exactly that distance, and keeps
    the break line beyond it. Only positive current values are adjusted; the change is noted in the
    driver text so it is visible."""
    ev = latest_by_indicator(evidence)
    out: list[Driver] = []
    for d in drivers:
        e = ev.get(d.indicator or "")
        if (
            d.kind != "metric"
            or e is None
            or e.value is None
            or e.value <= 0
            or d.warn_threshold is None
        ):
            out.append(d)
            continue
        v, w, good_high = e.value, d.warn_threshold, d.direction == "gte"
        new = v * (1 - MAX_WARN_GAP) if good_high else v * (1 + MAX_WARN_GAP)
        too_far = w < new if good_high else w > new
        if not too_far:
            out.append(d)
            continue
        new = round(new, 2)
        brk = d.break_threshold
        if brk is not None and (brk > new if good_high else brk < new):
            brk = round(new * (0.85 if good_high else 1.15), 2)
        out.append(
            d.model_copy(
                update={
                    "warn_threshold": new,
                    "break_threshold": brk,
                    "statement": f"{d.statement} (warn line tightened by code from {w:g} to {new:g}.)",
                }
            )
        )
    return out


QM_ID = re.compile(r"^QM\d+$")

# (indicator, direction, warn line, adverse test, text). Deliberately blunt: a WATCH only stops adds
# and asks for a look; one-offs (tax, write-downs) are for the reader to explain, not for code to guess.
_QUARTER_CHECKS = [
    (
        "q_sales_yoy",
        "gte",
        0.0,
        lambda v: v < 0,
        "Revenue in the latest quarter should not fall year on year.",
    ),
    (
        "q_np_yoy",
        "gte",
        -25.0,
        lambda v: v < -25,
        "Net profit in the latest quarter should not fall more than 25% year on year.",
    ),
    (
        "q_npm_chg",
        "gte",
        -5.0,
        lambda v: v < -5,
        "Net margin in the latest quarter should not fall more than 5 points year on year.",
    ),
    (
        "q_np_vs_med4",
        "gte",
        -40.0,
        lambda v: v < -40,
        "Net profit in the latest quarter should not be more than 40% below the median of the previous four quarters.",
    ),
    (
        "q_np_down_run",
        "lte",
        2.0,
        lambda v: v > 2,
        "Profit should not be lower than a year earlier for three quarters running.",
    ),
]


def quarterly_drivers(drivers: list[Driver], evidence: list[Evidence]) -> list[Driver]:
    """Code-owned monitors for the newest reported quarters. Unlike annual drivers they are not
    frozen: they are rebuilt on every run from current evidence, appear only while a quarter is
    adverse, and vanish when it recovers. They can only add a WATCH, never loosen a thesis, so the
    pre-registration rule is not weakened. Ids are QM1.. so they can be told apart and replaced."""
    ev = latest_by_indicator(evidence)
    have = {d.indicator for d in drivers if d.indicator and not QM_ID.match(d.id)}
    out: list[Driver] = []
    for key, direction, warn, adverse, text in _QUARTER_CHECKS:
        e = ev.get(key)
        if e is None or e.value is None or key in have or not adverse(e.value):
            continue
        out.append(
            Driver(
                id=f"QM{len(out) + 1}",
                statement=f"{text} (added by code: currently {e.value:g}.)",
                kind="metric",
                indicator=key,
                direction=direction,
                warn_threshold=warn,
                break_threshold=None,
                evidence_ids=[e.id],
            )
        )
    return out


def with_quarterly_drivers(drivers: list[Driver], evidence: list[Evidence]) -> list[Driver]:
    kept = [d for d in drivers if not QM_ID.match(d.id)]
    return kept + quarterly_drivers(kept, evidence)
