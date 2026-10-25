"""Thesis Analyst: one structured LLM call, then deterministic rules decide what is accepted."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from parakh_advisor.llm.client import LLM, LLMError
from parakh_advisor.metrics.quality import CompanyMetrics
from parakh_advisor.thesis import rules
from parakh_advisor.thesis.evidence import Evidence, digest, from_metrics
from parakh_advisor.thesis.models import (
    Change,
    ChangeDecision,
    Driver,
    KillCriterion,
    Risk,
    Thesis,
)

PROMPT_VERSION = "thesis_analyst@1"
_PROMPT = (Path(__file__).parent / "prompts" / "thesis_analyst_v1.md").read_text(encoding="utf-8")


def _user_message(
    name: str, sector: str | None, evidence: list[Evidence], prior: Thesis | None
) -> str:
    lines = [f"COMPANY: {name}", f"SECTOR: {sector or 'unknown'}", "", "EVIDENCE (cite by id):"]
    lines += [f"- {e.id} | as of {e.as_of} | {e.text}" for e in evidence]
    if prior:
        lines += [
            "",
            f"PRIOR THESIS (version {prior.version}, data as of {prior.as_of_data_date}):",
            prior.model_dump_json(
                include={"business_summary", "why_own", "drivers", "kill_criteria", "risks"}
            ),
        ]
    else:
        lines += ["", "There is no prior thesis. Use decision NEW."]
    return "\n".join(lines)


def _clean_ids(ids: list[str], valid: set[str]) -> list[str]:
    return [i for i in ids if i in valid]


def run(
    llm: LLM,
    instrument_id: str,
    name: str,
    sector: str | None,
    metrics: CompanyMetrics,
    prior: Thesis | None,
    documents: list[Evidence] | None = None,
) -> Thesis:
    evidence = from_metrics(metrics) + list(documents or [])
    if not evidence:
        raise LLMError(f"{name}: no evidence available (no metrics); cannot write a thesis")
    valid = {e.id for e in evidence}
    resp = llm.complete_json(_PROMPT, _user_message(name, sector, evidence, prior))
    data_date = max(e.as_of for e in evidence)
    dig = digest(evidence)
    version = (prior.version + 1) if prior else 1

    try:
        changes = [Change(**c) for c in resp.get("changes", [])]
        decision = ChangeDecision(resp.get("decision", "NEW" if prior is None else "REAFFIRM"))
        if prior is None:
            drivers = [
                Driver(**{**d, "evidence_ids": _clean_ids(d.get("evidence_ids", []), valid)})
                for d in resp["drivers"]
            ]
            kills = [KillCriterion(**k) for k in resp["kill_criteria"]]
            risks = [
                Risk(
                    statement=r["statement"],
                    evidence_ids=_clean_ids(r.get("evidence_ids", []), valid),
                )
                for r in resp["risks"]
            ]
            summary, why = resp["business_summary"], resp["why_own"]
            decision, kept, rejected = ChangeDecision.NEW, [], []
        else:
            decision, kept, rejected = rules.validate_change(prior, decision, changes, evidence)
            drivers, kills = (
                prior.drivers,
                prior.kill_criteria,
            )  # pre-registered: frozen unless REPLACE
            summary, why, risks = prior.business_summary, prior.why_own, prior.risks
            if kept and decision == ChangeDecision.AMEND:
                summary, why = resp.get("business_summary", summary), resp.get("why_own", why)
                risks = [
                    Risk(
                        statement=r["statement"],
                        evidence_ids=_clean_ids(r.get("evidence_ids", []), valid),
                    )
                    for r in resp.get("risks", [])
                ] or risks
            if kept and decision == ChangeDecision.REPLACE:
                drivers = [
                    Driver(**{**d, "evidence_ids": _clean_ids(d.get("evidence_ids", []), valid)})
                    for d in resp["drivers"]
                ]
                kills = [KillCriterion(**k) for k in resp["kill_criteria"]]
                summary, why = resp["business_summary"], resp["why_own"]
                risks = [
                    Risk(
                        statement=r["statement"],
                        evidence_ids=_clean_ids(r.get("evidence_ids", []), valid),
                    )
                    for r in resp["risks"]
                ]
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise LLMError(f"{name}: model output did not match the thesis schema: {exc}") from exc

    if len(drivers) < 2 or len(kills) < 1 or len(risks) < 1:
        raise LLMError(f"{name}: thesis needs at least 2 drivers, 1 kill criterion and 1 risk")

    if prior is None or decision == ChangeDecision.REPLACE:
        drivers = rules.tighten_drivers(list(drivers), evidence)
        drivers = drivers + rules.hygiene_drivers(drivers, evidence, metrics.profile)
    drivers, kills = rules.evaluate(list(drivers), list(kills), evidence)
    drivers, bad_flags = rules.apply_flags(drivers, resp.get("driver_flags", []), evidence)
    rejected = list(rejected) + bad_flags
    stance, conf = rules.derive_stance(
        drivers,
        kills,
        metrics.quarters_reported,
        # a filing counts as a source only if it is not stale (about 13 months) next to the newest evidence
        sourced=any(e.kind != "metric" and (data_date - e.as_of).days <= 400 for e in evidence),
        no_earnings_record=(
            metrics.ttm_profit is not None
            and metrics.ttm_profit <= 0
            and metrics.profitable_years < 2
        ),
    )
    return Thesis(
        instrument_id=instrument_id,
        version=version,
        as_of_data_date=data_date,
        model=llm.model,
        prompt_version=PROMPT_VERSION,
        inputs_digest=dig,
        business_summary=summary,
        why_own=why,
        drivers=drivers,
        kill_criteria=kills,
        risks=risks,
        stance=stance,
        confidence=conf,
        change_decision=decision,
        change_log=kept,
        rejected_changes=rejected,
    )
