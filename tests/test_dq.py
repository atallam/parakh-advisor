def codes(portfolio, code):
    return [f for f in portfolio.flags if f.code == code]


def test_dq01_cost_pending_for_equity_not_for_context(portfolio):
    ids = {f.instrument_id for f in codes(portfolio, "DQ-01")}
    assert "INE000000001" in ids
    assert "US:ACME" not in ids  # has a cost
    assert all(i is not None for i in ids)


def test_dq02_position_older_than_30_days(portfolio):
    ids = {f.instrument_id for f in codes(portfolio, "DQ-02")}
    assert "INE000000001" in ids  # CAS 31 Aug vs 21 Oct
    assert "US:ACME" not in ids  # SnapTrade 1 Oct, 20 days


def test_dq04_flags_implausible_cost_ratio(portfolio):
    ids = {f.instrument_id for f in codes(portfolio, "DQ-04")}
    assert "US:GAMMA" in ids  # 50x its recorded cost
    assert "US:ACME" not in ids  # exactly 10x is allowed (rule is strictly greater)
    assert "US:BETA" not in ids  # ordinary gain


def test_dq05_bse_listing(portfolio):
    assert {f.instrument_id for f in codes(portfolio, "DQ-05")} >= {"INE000000002"}


def test_dq06_generic_fund_name(portfolio):
    assert codes(portfolio, "DQ-06")


def test_dq07_tata_motors_lineage(portfolio):
    assert len(codes(portfolio, "DQ-07")) == 1


def test_dq08_asset_class_empty(portfolio):
    assert len(codes(portfolio, "DQ-08")) == 1
