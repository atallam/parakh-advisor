"""Quarterly drivers: latest-quarter signals measured against the same quarter a year earlier."""

from datetime import date

import pytest
from test_screener_metrics import _workbook

from parakh_advisor.agents import thesis_analyst
from parakh_advisor.llm.client import FakeLLM
from parakh_advisor.metrics.quality import Metric, compute, quarterly_metrics
from parakh_advisor.sources.india.screener_export import Table, read_screener
from parakh_advisor.thesis.evidence import Evidence, from_metrics
from parakh_advisor.thesis.models import Driver
from parakh_advisor.thesis.rules import quarterly_drivers, with_quarterly_drivers

D = [date(2025, 9, 30), date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)]
D9 = [date(2024, 9, 30), date(2024, 12, 31), date(2025, 3, 31), date(2025, 6, 30), *D]


def _q(sales, profit, dates=D):
    return Table(
        dates=list(dates), cols=list(range(len(dates))), rows={"Sales": sales, "Net profit": profit}
    )


def _get(ms, key):
    return next(m for m in ms if m.key == key)


def test_yoy_numbers_are_exact():
    ms = quarterly_metrics(_q([100, 110, 120, 130, 90], [20, 22, 24, 26, 9]))
    assert _get(ms, "q_sales_yoy").value == -10.0  # 90 vs 100
    assert _get(ms, "q_np_yoy").value == -55.0  # 9 vs 20
    assert _get(ms, "q_npm_chg").value == pytest.approx(-10.0)  # 10% vs 20%
    assert "Sep 2026 vs Sep 2025" in _get(ms, "q_np_yoy").basis


def test_down_run_counts_consecutive_quarters_below_a_year_earlier():
    one = quarterly_metrics(_q([100] * 9, [10, 10, 10, 10, 9, 9, 9, 12, 8], D9))
    assert _get(one, "q_np_down_run").value == 1  # newest is down, the one before is up
    four = quarterly_metrics(_q([100] * 9, [10, 10, 10, 10, 9, 9, 9, 9, 8], D9))
    assert _get(four, "q_np_down_run").value == 4  # capped at 4


def test_no_year_ago_quarter_gives_na_with_reason():
    ms = quarterly_metrics(_q([100, 110], [10, 11], D[:2]))
    assert all(m.value is None and m.note for m in ms)


def test_year_ago_loss_is_na_not_a_huge_percentage():
    m = _get(quarterly_metrics(_q([100, 1, 1, 1, 100], [-5, 1, 1, 1, 10])), "q_np_yoy")
    assert m.value is None and "not positive" in (m.note or "")


def test_nan_sales_do_not_crash():
    nan = float("nan")
    ms = quarterly_metrics(_q([nan] * 5, [1, 1, 1, 1, 1]))
    assert _get(ms, "q_sales_yoy").value is None and _get(ms, "q_np_yoy").value == 0.0


def _ev(key, value):
    return Evidence(
        id=f"MET.{key}@202609",
        kind="metric",
        text=f"{key} {value}",
        value=value,
        as_of=date(2026, 9, 30),
        source="t",
    )


def test_adverse_quarters_add_watch_drivers_and_healthy_ones_add_nothing():
    bad = [
        _ev("q_sales_yoy", -3.0),
        _ev("q_np_yoy", -40.0),
        _ev("q_npm_chg", -8.0),
        _ev("q_np_down_run", 3),
    ]
    assert [d.indicator for d in quarterly_drivers([], bad)] == [
        "q_sales_yoy",
        "q_np_yoy",
        "q_npm_chg",
        "q_np_down_run",
    ]
    good = [
        _ev("q_sales_yoy", 5.0),
        _ev("q_np_yoy", -10.0),
        _ev("q_npm_chg", -2.0),
        _ev("q_np_down_run", 2),
    ]
    assert quarterly_drivers([], good) == []


def test_boundaries_are_strict():
    edge = [
        _ev("q_sales_yoy", 0.0),
        _ev("q_np_yoy", -25.0),
        _ev("q_npm_chg", -5.0),
        _ev("q_np_down_run", 2),
    ]
    assert quarterly_drivers([], edge) == []


def test_missing_values_never_trip():
    assert quarterly_drivers([], [_ev("q_np_yoy", None)]) == []


def _with(metrics, **vals):
    keep = [m for m in metrics.metrics if m.key not in vals]
    extra = [Metric(key=k, label=k, value=v, unit="%", basis="test") for k, v in vals.items()]
    return metrics.model_copy(update={"metrics": keep + extra})


@pytest.fixture
def base(tmp_path):
    return compute(read_screener(_workbook(tmp_path / "a.xlsx")))


NEW = {
    "decision": "NEW",
    "business_summary": "s",
    "why_own": "w",
    "drivers": [
        {
            "id": "D1",
            "statement": "ROE",
            "kind": "metric",
            "indicator": "roe",
            "direction": "gte",
            "warn_threshold": 5,
            "break_threshold": 1,
        },
        {
            "id": "D2",
            "statement": "Debt",
            "kind": "metric",
            "indicator": "debt_equity",
            "direction": "lte",
            "warn_threshold": 1,
            "break_threshold": 2,
        },
    ],
    "kill_criteria": [
        {"id": "K1", "description": "d", "indicator": "debt_equity", "op": ">", "threshold": 5}
    ],
    "risks": [{"statement": "r"}],
}


def test_bad_quarter_adds_watch_to_a_new_thesis(base):
    t = thesis_analyst.run(FakeLLM(NEW), "X", "T", None, _with(base, q_np_yoy=-40.0), None)
    qm = [d for d in t.drivers if d.id.startswith("QM")]
    assert [d.indicator for d in qm] == ["q_np_yoy"] and qm[0].status == "WATCH"
    assert qm[0].evidence_ids and qm[0].break_threshold is None


def test_quarter_monitors_reach_existing_theses_and_vanish_on_recovery(base):
    prior = thesis_analyst.run(FakeLLM(NEW), "X", "T", None, _with(base, q_np_yoy=10.0), None)
    assert not any(d.id.startswith("QM") for d in prior.drivers)
    reaff = {**NEW, "decision": "REAFFIRM"}
    bad = thesis_analyst.run(FakeLLM(reaff), "X", "T", None, _with(base, q_np_yoy=-40.0), prior)
    assert [d.id for d in bad.drivers if d.id.startswith("QM")] == ["QM1"]
    assert [d.id for d in bad.drivers[:2]] == ["D1", "D2"]  # frozen drivers untouched
    healed = thesis_analyst.run(FakeLLM(reaff), "X", "T", None, _with(base, q_np_yoy=3.0), bad)
    assert not any(d.id.startswith("QM") for d in healed.drivers)


def test_model_driver_on_the_same_indicator_is_respected():
    mine = [Driver(id="D9", statement="x", kind="metric", indicator="q_np_yoy", direction="gte")]
    assert quarterly_drivers(mine, [_ev("q_np_yoy", -50.0)]) == []
    old = Driver(id="QM1", statement="old", kind="metric", indicator="q_np_yoy", direction="gte")
    assert with_quarterly_drivers([old], [_ev("q_np_yoy", 5.0)]) == []


def test_evidence_period_uses_quarter_end(base):
    ids = {e.id for e in from_metrics(base)}
    assert f"MET.q_np_yoy@{base.quarter_end:%Y%m}" in ids
