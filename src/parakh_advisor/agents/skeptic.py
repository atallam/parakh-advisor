"""Skeptic: a real tool-using loop (bounded), then deterministic validation of what it says.

The model chooses which tool to call each turn (metric, peers, search_docs, get). The loop ends at a
final answer or at MAX_TOOL_CALLS, whichever is first. The Skeptic writes the counter-case only; it
cannot touch drivers, thresholds or stance.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from parakh_advisor.llm.client import LLM, LLMError
from parakh_advisor.thesis.evidence import Evidence, latest_by_indicator
from parakh_advisor.thesis.models import Thesis

MAX_TOOL_CALLS = 4
PROMPT_VERSION = "skeptic@1"
_PROMPT = (Path(__file__).parent / "prompts" / "skeptic_v1.md").read_text(encoding="utf-8")


class Point(BaseModel):
    point: str
    evidence_ids: list[str]


class SkepticResult(BaseModel):
    counter_case: str
    points: list[Point]
    would_change_my_mind: str
    tool_calls: int
    rejected: list[str] = []


class Tools:
    """The Skeptic's tools. Read-only, deterministic, and limited to what is passed in."""

    def __init__(self, own: list[Evidence], cohort: dict[str, list[Evidence]], self_name: str):
        self.own, self.cohort, self.self_name = own, cohort, self_name
        self.seen: set[str] = set()

    def run(self, tool: str, args: dict) -> str:
        if tool == "metric":
            e = latest_by_indicator(self.own).get(str(args.get("key", "")))
            if e is None:
                return "no such metric for this company"
            self.seen.add(e.id)
            return f"{e.id}: {e.text}"
        if tool == "get":
            e = next((x for x in self.own if x.id == args.get("id")), None)
            if e is None:
                return "unknown evidence id"
            self.seen.add(e.id)
            return f"{e.id} (as of {e.as_of}, {e.source}): {e.text}"
        if tool == "peers":
            key = str(args.get("key", ""))
            rows = []
            for name, ev in self.cohort.items():
                if name == self.self_name:
                    continue
                e = latest_by_indicator(ev).get(key)
                if e is not None and e.value is not None:
                    rows.append(f"{name}: {e.value}")
            return f"cohort of {len(rows)} other holdings (not a sector). " + (
                "; ".join(rows) if rows else "no peer has this metric"
            )
        if tool == "search_docs":
            term = str(args.get("term", "")).lower()
            hits = [e for e in self.own if e.kind != "metric" and term and term in e.text.lower()][
                :3
            ]
            for e in hits:
                self.seen.add(e.id)
            return (
                "\n".join(f"{e.id}: {e.text[:400]}" for e in hits)
                or "no passage contains that term"
            )
        return f"unknown tool {tool!r}; use metric, peers, search_docs or get"


def run(
    llm: LLM, thesis: Thesis, name: str, own: list[Evidence], cohort: dict[str, list[Evidence]]
) -> SkepticResult:
    tools = Tools(own, cohort, name)
    brief = thesis.model_dump_json(
        include={"business_summary", "why_own", "drivers", "kill_criteria", "risks", "stance"}
    )
    index = "\n".join(f"- {e.id}: {e.text[:160]}" for e in own if e.kind == "metric")
    transcript = f"COMPANY: {name}\n\nTHESIS:\n{brief}\n\nEVIDENCE INDEX (metrics):\n{index}\n"
    calls = 0
    for _ in range(MAX_TOOL_CALLS + 2):
        resp = llm.complete_json(
            _PROMPT, transcript + "\nTOOL CALLS USED: " + str(calls) + f" of {MAX_TOOL_CALLS}"
        )
        action = resp.get("action")
        if action == "tool":
            if calls >= MAX_TOOL_CALLS:
                transcript += "\nBUDGET EXHAUSTED. Reply now with action final.\n"
                continue
            calls += 1
            out = tools.run(str(resp.get("tool")), resp.get("args") or {})
            transcript += (
                f"\nTOOL {resp.get('tool')} {json.dumps(resp.get('args') or {})} ->\n{out}\n"
            )
            continue
        if action == "final":
            return _validate(resp, own, tools.seen, calls)
        raise LLMError(f"{name}: Skeptic returned an unusable action: {resp.get('action')!r}")
    raise LLMError(f"{name}: Skeptic did not finish within its turn budget")


def _validate(resp: dict, own: list[Evidence], seen: set[str], calls: int) -> SkepticResult:
    valid = {e.id for e in own}
    rejected: list[str] = []
    points: list[Point] = []
    for p in resp.get("points", []):
        ids = [i for i in p.get("evidence_ids", []) if i in valid]
        dropped = [i for i in p.get("evidence_ids", []) if i not in valid]
        if dropped:
            rejected.append(f"dropped unknown evidence ids {dropped}")
        if not ids:
            rejected.append(f"dropped a point with no valid evidence: {str(p.get('point'))[:60]}")
            continue
        points.append(Point(point=str(p["point"]), evidence_ids=ids))
    case = str(resp.get("counter_case", "")).strip()
    if not case:
        raise LLMError("Skeptic gave no counter_case")
    if len(case.split()) > 160:
        words = case.split()
        case = " ".join(words[:120]) + " ..."
        rejected.append("counter_case trimmed to 120 words")
    return SkepticResult(
        counter_case=case,
        points=points,
        would_change_my_mind=str(resp.get("would_change_my_mind", "")),
        tool_calls=calls,
        rejected=rejected,
    )
