from datetime import UTC, date

from parakh_advisor.metrics.quality import compute
from parakh_advisor.sources.us.edgar import shares_outstanding, to_company


def fact(start, end, val, fp, form="10-K"):
    return {"start": start, "end": end, "val": val, "fp": fp, "form": form, "filed": end}


def inst(end, val):
    return {"end": end, "val": val, "form": "10-K", "filed": end}


def facts():
    ni = [
        fact(f"{y}-01-01", f"{y}-12-31", v, "FY")
        for y, v in [(2022, 100e6), (2023, 120e6), (2024, 150e6), (2025, 200e6)]
    ]
    ni += [
        fact("2025-04-01", "2026-03-31", 999e6, "Q1", "10-Q")
    ]  # a trailing-twelve-month window: must be ignored
    q = [
        ("2025-01-01", "2025-03-31", 30e6),
        ("2025-04-01", "2025-06-30", 40e6),
        ("2025-07-01", "2025-09-30", 50e6),
        ("2026-01-01", "2026-03-31", 60e6),
    ]
    ni += [
        fact(
            s, e, v, "Q1" if e.endswith("03-31") else "Q2" if e.endswith("06-30") else "Q3", "10-Q"
        )
        for s, e, v in q
    ]
    rev = [
        fact(f"{y}-01-01", f"{y}-12-31", v, "FY")
        for y, v in [(2022, 1000e6), (2023, 1100e6), (2024, 1300e6), (2025, 1600e6)]
    ]
    us = {
        "NetIncomeLoss": {"units": {"USD": ni}},
        "Revenues": {"units": {"USD": rev}},
        "StockholdersEquity": {
            "units": {"USD": [inst(f"{y}-12-31", 500e6) for y in (2022, 2023, 2024, 2025)]}
        },
        "OperatingIncomeLoss": {
            "units": {
                "USD": [
                    fact(f"{y}-01-01", f"{y}-12-31", 120e6, "FY") for y in (2022, 2023, 2024, 2025)
                ]
            }
        },
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": {
            "units": {
                "USD": [
                    fact(f"{y}-01-01", f"{y}-12-31", 130e6, "FY") for y in (2022, 2023, 2024, 2025)
                ]
            }
        },
    }
    us["DepreciationDepletionAndAmortization"] = {
        "units": {
            "USD": [fact(f"{y}-01-01", f"{y}-12-31", 10e6, "FY") for y in (2022, 2023, 2024, 2025)]
        }
    }
    return {"facts": {"us-gaap": us, "dei": {}}}


def test_ttm_windows_are_not_mistaken_for_fiscal_years():
    c = to_company("TESTCO", facts(), 10.0)
    assert c.annual.dates[-1] == date(2025, 12, 31) and c.annual.get("Net profit")[-1] == 200.0
    assert c.money_unit == "USD m"


def test_q4_is_derived_from_the_year_minus_three_quarters():
    c = to_company("TESTCO", facts(), 10.0)
    q = dict(zip(c.quarters.dates, c.quarters.get("Net profit"), strict=True))
    assert q[date(2025, 12, 31)] == 200.0 - (30 + 40 + 50)


def test_operating_margin_is_operating_income_plus_depreciation_over_revenue():
    m = compute(to_company("TESTCO", facts(), 10.0))
    assert abs(m.get("op_margin").value - 8.125) < 0.02  # (120 + 10) / 1600
    assert m.get("np_fy").unit == "USD m"


def test_share_count_falls_back_when_cover_page_is_missing():
    f = {
        "facts": {
            "us-gaap": {
                "CommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"end": "2026-03-31", "val": 2.0e9},
                            {"end": "2025-12-31", "val": 1.9e9},
                        ]
                    }
                }
            }
        }
    }
    assert shares_outstanding(f) == 2.0e9


# --- Day 6a: price history ---
def test_month_end_prices_undo_later_splits():
    from datetime import datetime

    from parakh_advisor.sources.us.prices import month_end_prices

    ts = lambda y, m, d: int(datetime(y, m, d, tzinfo=UTC).timestamp())  # noqa: E731
    data = {
        "chart": {
            "result": [
                {
                    "timestamp": [ts(2024, 1, 1), ts(2024, 5, 1), ts(2024, 7, 1)],
                    "indicators": {"quote": [{"close": [12.0, 100.0, 110.0]}]},
                    "events": {
                        "splits": {
                            "x": {"date": ts(2024, 6, 10), "numerator": 10, "denominator": 1}
                        }
                    },
                }
            ]
        }
    }
    p = month_end_prices(data)
    assert p[(2024, 1)] == 120.0 and p[(2024, 5)] == 1000.0  # quoted at the time, pre-split
    assert p[(2024, 7)] == 110.0  # after the split: unchanged


def test_diluted_shares_use_first_reported():
    from parakh_advisor.sources.us.edgar import diluted_shares_first_reported

    us = {
        "WeightedAverageNumberOfDilutedSharesOutstanding": {
            "units": {
                "shares": [
                    {
                        "start": "2022-01-01",
                        "end": "2022-12-31",
                        "fp": "FY",
                        "filed": "2023-02-01",
                        "val": 100,
                    },
                    {
                        "start": "2022-01-01",
                        "end": "2022-12-31",
                        "fp": "FY",
                        "filed": "2024-02-01",
                        "val": 1000,
                    },
                ]
            }
        }
    }
    from datetime import date

    assert diluted_shares_first_reported(us)[date(2022, 12, 31)] == 100.0
