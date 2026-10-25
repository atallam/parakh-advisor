"""Reverse DCF: maths, edge cases, and how it combines with the own-history reading."""

import pytest

from parakh_advisor.advice.valuation import valuation_stance
from parakh_advisor.metrics import rdcf
from parakh_advisor.metrics.quality import CompanyMetrics, Metric


def test_zero_growth_value_matches_hand_calculation():
    # 100 a year for 10 years at 10%, then 3% forever: 614.46 + 1471.43 / 1.1**10
    assert rdcf.present_value(100, 0.0, 0.10, 0.03) == pytest.approx(1181.3, abs=0.5)


def test_solver_round_trips():
    for g in (-0.05, 0.0, 0.08, 0.20):
        value = rdcf.present_value(250, g, 0.15, 0.05)
        solved, edge = rdcf.implied_growth(value, 250, 0.15, 0.05)
        assert edge is None and solved == pytest.approx(g, abs=1e-6)


def test_more_expensive_means_higher_implied_growth():
    cheap, _ = rdcf.implied_growth(1000, 100, 0.10, 0.03)
    dear, _ = rdcf.implied_growth(3000, 100, 0.10, 0.03)
    assert dear > cheap


def test_a_higher_discount_rate_asks_for_more_growth():
    low, _ = rdcf.implied_growth(2000, 100, 0.10, 0.03)
    high, _ = rdcf.implied_growth(2000, 100, 0.15, 0.05)
    assert high > low


def test_search_limits_are_reported_not_hidden():
    g, edge = rdcf.implied_growth(1e12, 1, 0.10, 0.03)
    assert edge == "high" and g == rdcf.HI
    g, edge = rdcf.implied_growth(0.001, 100, 0.10, 0.03)
    assert edge == "low" and g == rdcf.LO


def test_profit_base_is_the_lower_and_must_be_positive():
    assert rdcf.profit_base(100, 150) == (100, "last fiscal year")
    assert rdcf.profit_base(150, 100) == (100, "trailing 4 quarters")
    assert rdcf.profit_base(100, None) == (100, "last fiscal year")
    assert rdcf.profit_base(-5, 100)[0] is None and rdcf.profit_base(None, None)[0] is None


@pytest.mark.parametrize(
    "implied,gap,want",
    [
        (10, -8.0, "CHEAP"),
        (10, -7.9, "FAIR"),
        (10, 4.9, "FAIR"),
        (10, 5.0, "RICH"),
        (10, 11.9, "RICH"),
        (10, 12.0, "STRETCHED"),
        (25.1, -30.0, "STRETCHED"),  # ten years of 25%+ growth is a tenfold profit
        (10, None, "NA"),
    ],
)
def test_stance_boundaries(implied, gap, want):
    assert rdcf.stance_from_gap(implied, gap) == want


def _m(pe_vs_hist=None, growth=None, gap=None):
    def mk(k, v):
        return Metric(key=k, label=k, value=v, unit="%", basis="b")

    ms = [mk("pe_vs_hist", pe_vs_hist), mk("rdcf_growth", growth), mk("rdcf_gap", gap)]
    return CompanyMetrics(
        name="X",
        profile="standard",
        fy_end=None,
        quarter_end=None,
        price=None,
        market_cap_cr=None,
        metrics=ms,
    )


def test_more_cautious_reading_wins():
    assert valuation_stance(_m(-30, 12, -2))[0] == "FAIR"  # history says cheap, DCF says fair
    assert valuation_stance(_m(0, 20, 8))[0] == "RICH"  # history fair, DCF rich
    assert valuation_stance(_m(-30, 5, -15))[0] == "CHEAP"  # both agree


def test_one_reading_alone_still_gives_an_answer_and_says_so():
    v, why = valuation_stance(_m(None, 12, -10))
    assert v == "CHEAP" and "Reverse DCF only" in why
    v, why = valuation_stance(_m(-30, None, None))
    assert v == "CHEAP" and "Own history only" in why


def test_both_unreadable_is_na():
    assert valuation_stance(_m(None, None, None))[0] == "NA"


def test_unreliable_history_uses_only_the_absolute_ask():
    # merger-distorted company: past growth is not comparable, so a modest ask cannot say CHEAP
    assert valuation_stance(_m(-50, 12, -20), history_reliable=False)[0] == "NA"
    assert valuation_stance(_m(-50, 30, -20), history_reliable=False)[0] == "STRETCHED"


def test_compute_produces_metrics_that_round_trip_to_market_value(tmp_path):
    from test_screener_metrics import _workbook

    from parakh_advisor.metrics.quality import compute
    from parakh_advisor.sources.india.screener_export import read_screener

    c = read_screener(_workbook(tmp_path / "a.xlsx"))
    m = compute(c)
    g, gap = m.get("rdcf_growth"), m.get("rdcf_gap")
    assert g and g.value is not None and gap and gap.value is not None
    base, _ = rdcf.profit_base(m.get("np_fy").value, m.ttm_profit)
    pv = rdcf.present_value(base, g.value / 100, 0.15, 0.05)  # India: 15% / 5%
    assert pv == pytest.approx(c.market_cap, rel=0.01)
    assert "15% discount" in g.basis


def test_us_company_uses_us_rates(tmp_path):
    from dataclasses import replace

    from test_screener_metrics import _workbook

    from parakh_advisor.metrics.quality import compute
    from parakh_advisor.sources.india.screener_export import read_screener

    c = replace(read_screener(_workbook(tmp_path / "a.xlsx")), money_unit="USD m")
    assert "10% discount, 3% terminal" in compute(c).get("rdcf_growth").basis


def test_loss_making_company_is_na_with_reason(tmp_path):
    from test_screener_metrics import _workbook

    from parakh_advisor.metrics.quality import compute
    from parakh_advisor.sources.india.screener_export import read_screener

    c = read_screener(_workbook(tmp_path / "a.xlsx"))
    c.annual.rows["Net profit"][-1] = -10.0
    g = compute(c).get("rdcf_growth")
    assert g.value is None and "not positive" in (g.note or "")
