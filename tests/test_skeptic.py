import pytest
from test_screener_metrics import _workbook
from test_thesis import NEW

from parakh_advisor.agents import skeptic, thesis_analyst
from parakh_advisor.llm.client import FakeLLM, LLMError
from parakh_advisor.metrics.quality import compute
from parakh_advisor.sources.india.screener_export import read_screener
from parakh_advisor.thesis.evidence import from_metrics


@pytest.fixture
def setup(tmp_path):
    m = compute(read_screener(_workbook(tmp_path / "a.xlsx")))
    th = thesis_analyst.run(FakeLLM(NEW), "X", "TESTCO", None, m, None)
    ev = from_metrics(m)
    return th, ev


def final(**kw):
    return {
        "action": "final",
        "counter_case": "Margins are at a peak.",
        "points": [{"point": "p", "evidence_ids": ["MET.roe@202603"]}],
        "would_change_my_mind": "Two more good years.",
        **kw,
    }


def test_loop_calls_tools_then_finishes(setup):
    th, ev = setup
    llm = FakeLLM(
        {"action": "tool", "tool": "metric", "args": {"key": "roe"}},
        {"action": "tool", "tool": "peers", "args": {"key": "roe"}},
        final(),
    )
    r = skeptic.run(llm, th, "TESTCO", ev, {"TESTCO": ev, "OTHER": ev})
    assert r.tool_calls == 2 and r.points and "MET.roe@202603" in r.points[0].evidence_ids
    assert "TOOL metric" in llm.calls[-1][1] and "cohort of" in llm.calls[-1][1]


def test_tool_budget_is_enforced(setup):
    th, ev = setup
    tool = {"action": "tool", "tool": "metric", "args": {"key": "roe"}}
    llm = FakeLLM(*[tool] * 5, final())
    r = skeptic.run(llm, th, "TESTCO", ev, {})
    assert r.tool_calls == skeptic.MAX_TOOL_CALLS


def test_never_finishing_raises(setup):
    th, ev = setup
    tool = {"action": "tool", "tool": "metric", "args": {"key": "roe"}}
    with pytest.raises(LLMError):
        skeptic.run(FakeLLM(*[tool] * 10), th, "TESTCO", ev, {})


def test_unknown_evidence_is_dropped_and_logged(setup):
    th, ev = setup
    r = skeptic.run(
        FakeLLM(
            final(
                points=[
                    {"point": "x", "evidence_ids": ["MET.fake@1"]},
                    {"point": "y", "evidence_ids": ["MET.roe@202603", "MET.fake@1"]},
                ]
            )
        ),
        th,
        "TESTCO",
        ev,
        {},
    )
    assert len(r.points) == 1 and r.rejected


def test_unknown_tool_is_reported_not_crashed(setup):
    th, ev = setup
    llm = FakeLLM({"action": "tool", "tool": "web_search", "args": {}}, final())
    skeptic.run(llm, th, "TESTCO", ev, {})
    assert "unknown tool" in llm.calls[-1][1]
