import json

import pytest

from parakh_advisor.contracts.holdings_v2 import AssetClass
from parakh_advisor.ingest.normalise import clean_name, split_ticker
from parakh_advisor.ingest.wealthlens_json import ExportError, load_rows


def by_id(portfolio, iid):
    return next(p for p in portfolio.positions if p.instrument_id == iid)


def test_exited_rows_are_dropped(portfolio):
    assert all(p.instrument_id != "INE000000009" for p in portfolio.positions)


def test_names_are_cleaned():
    assert clean_name("INDIAN ENERGY EXCHANGE LIMITED#NEW") == "INDIAN ENERGY EXCHANGE LIMITED"
    assert (
        clean_name("ACTION CONSTRUCTION EQUIPMENTS LIMITED -")
        == "ACTION CONSTRUCTION EQUIPMENTS LIMITED"
    )


def test_tickers_split_exchange():
    assert split_ticker("M&M.NS") == ("M&M", "NSE")
    assert split_ticker("MAZDOCK.BO") == ("MAZDOCK", "BSE")
    assert split_ticker("SOFI") == ("SOFI", None)


def test_identity_keys(portfolio):
    assert by_id(portfolio, "INE000000001").asset_class == AssetClass.IN_EQUITY
    assert by_id(portfolio, "US:ACME").asset_class == AssetClass.US_EQUITY


def test_us_value_converts_to_inr(portfolio):
    acme = by_id(portfolio, "US:ACME")
    assert acme.value_inr == pytest.approx(10000 * 90)
    assert acme.cost_value_inr == pytest.approx(100 * 10 * 90)


def test_zero_cost_means_pending_not_zero(portfolio):
    big = by_id(portfolio, "INE000000001")
    assert big.cost_per_unit is None and big.cost_value_inr is None


def test_gold_etf_is_commodity_sleeve_outside_listed_equity(portfolio):
    gold = by_id(portfolio, "INF000000007")
    assert gold.asset_class == AssetClass.ETF and gold.sleeve == "commodity"
    assert not gold.is_listed_equity
    assert by_id(portfolio, "INF000000006").is_listed_equity


def test_fund_symbol_is_not_the_isin(portfolio):
    assert by_id(portfolio, "INF000000006").symbol is None


def test_context_assets_use_principal_and_fx_fallback(portfolio):
    fd = next(p for p in portfolio.positions if p.asset_class == AssetClass.FD)
    assert fd.value_inr == 200000
    cash = next(p for p in portfolio.positions if p.asset_class == AssetClass.CASH)
    assert cash.value_inr == pytest.approx(100 * 90)  # median FX from the US rows


def test_reference_date_is_newest_price_stamp(portfolio):
    assert str(portfolio.reference_date) == "2026-10-21"


def test_bad_inputs_give_clear_errors(tmp_path):
    with pytest.raises(ExportError):
        load_rows(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    with pytest.raises(ExportError):
        load_rows(bad)
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps([]))
    with pytest.raises(ExportError):
        load_rows(empty)
    nokeys = tmp_path / "nokeys.json"
    nokeys.write_text(json.dumps([{"foo": 1}]))
    with pytest.raises(ExportError):
        load_rows(nokeys)
