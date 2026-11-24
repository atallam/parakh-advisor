"""WealthLens CSV export: ISIN placement, USD conversion, and refusing when no rate exists."""

from __future__ import annotations

import pytest

from parakh_advisor.ingest.normalise import build_portfolio
from parakh_advisor.ingest.wealthlens_json import ExportError, load_rows
from parakh_advisor.sources.http import SourceError

HEADER = (
    "Name,Type,Member ID,Ticker,Scheme Code,Net Units,Avg Cost (INR),Invested (INR),"
    "Current Value (INR),Gain (INR),Gain %,XIRR %,Interest Rate %,Principal,Sum Assured,"
    "Premium,Premium Frequency,Currency,Policy Type,Start Date,Maturity Date,Source\n"
)
STOCK = "HDFC BANK LIMITED#NEW,IN_STOCK,m_1,HDFCBANK.NS,INE040A01034,100,,0,83440,0,,,,,,,ANNUAL,INR,,,,cas\n"
FUND = "Bandhan Small Cap Fund,MF,m_1,INF194KB1AL4,147946,11179.418,,0,632475,0,,,,,,,ANNUAL,INR,,,,cas\n"
US = "Amazon.com Inc.,US_STOCK,m_1,AMZN,,50,,0,12341,0,,,,,,,ANNUAL,USD,,2026-11-10,,snaptrade\n"


def _write(tmp_path, *rows: str):
    p = tmp_path / "h.csv"
    p.write_text(HEADER + "".join(rows), encoding="utf-8")
    return p


def test_isin_comes_from_scheme_code_for_stocks_and_ticker_for_funds(tmp_path, monkeypatch):
    monkeypatch.delenv("PARAKH_USD_INR", raising=False)
    rows = load_rows(_write(tmp_path, STOCK, FUND))
    assert rows[0]["isin"] == "INE040A01034" and rows[0]["scheme_code"] == ""
    assert rows[1]["isin"] == "INF194KB1AL4" and rows[1]["scheme_code"] == "147946"
    assert len({r["id"] for r in rows}) == 2


def test_us_value_is_converted_with_the_rate(tmp_path, monkeypatch):
    monkeypatch.setattr("parakh_advisor.ingest.wealthlens_json._default_usd_inr", lambda: 90.0)
    pf = build_portfolio(load_rows(_write(tmp_path, STOCK, US)))
    amzn = next(p for p in pf.positions if p.symbol == "AMZN")
    assert amzn.value_inr == pytest.approx(12341 * 90)


def test_no_rate_available_refuses_instead_of_zeroing_us(tmp_path, monkeypatch):
    def boom() -> float:
        raise SourceError("offline")

    monkeypatch.setattr("parakh_advisor.ingest.wealthlens_json._default_usd_inr", boom)
    with pytest.raises(ExportError, match="no exchange rate"):
        load_rows(_write(tmp_path, US))


def test_rate_not_fetched_without_usd_rows(tmp_path, monkeypatch):
    def boom() -> float:
        raise AssertionError("should not be called")

    monkeypatch.setattr("parakh_advisor.ingest.wealthlens_json._default_usd_inr", boom)
    assert len(load_rows(_write(tmp_path, STOCK, FUND))) == 2


def test_missing_columns_are_refused(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("Foo,Bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ExportError, match="missing CSV columns"):
        load_rows(p)


def test_unit_price_is_derived_from_value_and_units(tmp_path, monkeypatch):
    monkeypatch.setattr("parakh_advisor.ingest.wealthlens_json._default_usd_inr", lambda: 90.0)
    rows = load_rows(_write(tmp_path, STOCK, US))
    assert float(rows[0]["current_price"]) == pytest.approx(834.4)
    pf = build_portfolio(rows)
    assert next(p for p in pf.positions if p.symbol == "AMZN").price == pytest.approx(246.82)
