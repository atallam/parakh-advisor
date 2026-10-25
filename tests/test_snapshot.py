import pytest

from parakh_advisor.advice.policy import Policy
from parakh_advisor.advice.snapshot import RiskAction, build_snapshot


@pytest.fixture
def snap(portfolio, policy):
    return build_snapshot(portfolio, policy)


def h(snap, iid):
    return next(x for x in snap.holdings if x.instrument_id == iid)


def test_weights_of_listed_equity_sum_to_100(snap):
    total = sum(x.weight_pct for x in snap.holdings if x.weight_pct is not None)
    assert total == pytest.approx(100.0)


def test_gold_etf_excluded_from_listed_equity(snap):
    assert h(snap, "INF000000007").weight_pct is None


def test_same_isin_across_members_is_merged(snap):
    big = h(snap, "INE000000001")
    assert big.member_ids == ["m1", "m2"]
    assert big.units == 200


def test_member_filter_changes_the_denominator(portfolio, policy):
    only_m2 = build_snapshot(portfolio, policy, member="m2")
    assert only_m2.member_filter == "m2"
    assert all("m1" not in x.member_ids for x in only_m2.holdings)
    with pytest.raises(ValueError):
        build_snapshot(portfolio, policy, member="nobody")


def test_concentration_trim_and_amount_over_cap(snap, policy):
    acme = h(snap, "US:ACME")
    assert acme.action == RiskAction.TRIM and "CONCENTRATION" in acme.reason_codes
    expected = acme.value_inr - policy.single_name_cap_pct / 100 * snap.listed_equity_inr
    assert acme.amount_over_cap_inr == pytest.approx(expected)
    assert snap.top3_breach
    assert "ACME" in snap.single_name_breaches


def test_dust_is_flagged_only_below_threshold(snap):
    assert h(snap, "INE000000003").action == RiskAction.BUILD_OR_CONSOLIDATE
    assert "TINY" in snap.dust


def test_policy_change_changes_the_result(portfolio):
    loose = build_snapshot(portfolio, Policy(single_name_cap_pct=95, top3_cap_pct=100))
    assert not loose.single_name_breaches and not loose.top3_breach


def test_funds_get_review_not_trim(snap):
    fund = h(snap, "INF000000006")
    assert fund.action == RiskAction.REVIEW and "FUND_REVIEW_PENDING" in fund.reason_codes


def test_context_assets_are_not_advised(snap):
    fd = next(x for x in snap.holdings if x.asset_class.value == "FD")
    assert fd.action is None and fd.weight_pct is None


def test_pnl_blank_when_cost_pending(snap):
    assert h(snap, "INE000000001").pnl_pct is None
    assert h(snap, "US:BETA").pnl_pct == pytest.approx((100 / 95 - 1) * 100)


def test_cost_counts_and_verdict(snap):
    assert snap.cost_pending_count > 0 and snap.cost_tracked_count == 3
    assert len(snap.verdict) == 3
    assert "Concentration is the main issue" in snap.verdict[0]


def test_net_worth_includes_context_assets(snap):
    assert snap.net_worth_inr > snap.listed_equity_inr


def test_acknowledged_flag_is_removed_and_listed_once(portfolio, policy):
    flagged = next(f for f in portfolio.flags if f.instrument_id and f.code == "DQ-02")
    base = build_snapshot(portfolio, policy)
    assert any(f.code == "DQ-02" and f.instrument_id == flagged.instrument_id for f in base.flags)
    snap = build_snapshot(portfolio, policy, acknowledged={flagged.instrument_id: {"DQ-02"}})
    assert not any(
        f.code == "DQ-02" and f.instrument_id == flagged.instrument_id for f in snap.flags
    )
    assert any("DQ-02" in x for x in snap.acknowledged_flags)
    assert all(
        "DQ-02" not in c
        for x in snap.holdings
        if x.instrument_id == flagged.instrument_id
        for c in x.flag_codes
    )
