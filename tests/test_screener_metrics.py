from datetime import datetime

import openpyxl
import pytest

from parakh_advisor.metrics.quality import compute
from parakh_advisor.sources.india.screener_export import ScreenerError, read_screener

YEARS = [datetime(y, 3, 31) for y in (2022, 2023, 2024, 2025, 2026)]


def _workbook(path, name="TESTCO LTD", blank_first_year=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data Sheet"
    ws.append(["COMPANY NAME", name])
    ws.append(["CURRENT VERSION", "2.1"])
    ws.append([])
    ws.append(["META"])
    ws.append(["Current Price", 100.0])
    ws.append(["Market Capitalization", 1000.0])
    ws.append([])
    ws.append(["PROFIT & LOSS"])
    ws.append(["Report Date", *YEARS])
    ws.append(["Sales", *([None] if blank_first_year else [100.0]), 120.0, 140.0, 160.0, 200.0])
    ws.append(["Other Income", *([None] if blank_first_year else [5.0]), 5.0, 5.0, 5.0, 10.0])
    ws.append(["Depreciation", *([None] if blank_first_year else [10.0]), 10.0, 10.0, 10.0, 10.0])
    ws.append(["Interest", *([None] if blank_first_year else [4.0]), 4.0, 4.0, 4.0, 5.0])
    ws.append(
        ["Profit before tax", *([None] if blank_first_year else [30.0]), 35.0, 40.0, 45.0, 55.0]
    )
    ws.append(["Net profit", *([None] if blank_first_year else [22.0]), 26.0, 30.0, 34.0, 40.0])
    ws.append([])
    ws.append(["Quarters"])
    ws.append(
        [
            "Report Date",
            datetime(2025, 9, 30),
            datetime(2025, 12, 31),
            datetime(2026, 3, 31),
            datetime(2026, 6, 30),
        ]
    )
    ws.append(["Net profit", 10.0, 10.0, 10.0, 10.0])
    ws.append([])
    ws.append(["BALANCE SHEET"])
    ws.append(["Report Date", *YEARS])
    ws.append(["Equity Share Capital", 10, 10, 10, 10, 10])
    ws.append(["Reserves", 190, 200, 210, 240, 290])
    ws.append(["Borrowings", 50, 50, 50, 50, 60])
    ws.append([])
    ws.append(["CASH FLOW:"])
    ws.append(["Report Date", *YEARS])
    ws.append(["Cash from Operating Activity", 20, 20, 20, 30, 50])
    ws.append(["PRICE:", 50, 60, 70, 80, 90])
    ws.append(["DERIVED:"])
    ws.append(["Adjusted Equity Shares in Cr", 10, 10, 10, 10, 10])
    wb.save(path)
    return path


def test_loader_keys_on_company_name_not_filename(tmp_path):
    c = read_screener(_workbook(tmp_path / "abc123_whatever.xlsx"))
    assert c.name == "TESTCO LTD" and c.market_cap == 1000.0
    assert c.annual.get("Sales")[-1] == 200.0
    assert c.year_end_price.rows["Price"][-1] == 90.0
    assert len(c.derived.get("Adjusted Equity Shares in Cr")) == 5


def test_rejects_non_screener_workbook(tmp_path):
    wb = openpyxl.Workbook()
    wb.save(tmp_path / "x.xlsx")
    with pytest.raises(ScreenerError):
        read_screener(tmp_path / "x.xlsx")


def test_blank_leading_year_keeps_columns_aligned(tmp_path):
    c = read_screener(_workbook(tmp_path / "n.xlsx", blank_first_year=True))
    assert c.annual.get("Sales")[0] is None and c.annual.get("Sales")[-1] == 200.0


def test_metrics_hand_checked(tmp_path):
    m = compute(read_screener(_workbook(tmp_path / "a.xlsx")))
    # FY26 operating margin = (55 + 5 + 10 - 10) / 200 = 30%
    assert m.get("op_margin").value == 30.0
    # 3y revenue CAGR from FY23 (120) to FY26 (200)
    assert m.get("rev_cagr_3").value == pytest.approx(((200 / 120) ** (1 / 3) - 1) * 100, abs=0.01)
    # ROE = 40 / avg(300, 250)
    assert m.get("roe").value == pytest.approx(40 / 275 * 100, abs=0.01)
    assert m.get("debt_equity").value == pytest.approx(60 / 300, abs=0.01)
    assert m.get("pe_ttm").value == 25.0  # 1000 / (4 x 10)
    assert m.get("pb").value == pytest.approx(1000 / 300, abs=0.01)
    assert m.get("cfo_np").value == 1.25


def test_bank_profile_marks_inapplicable_ratios(tmp_path):
    m = compute(read_screener(_workbook(tmp_path / "b.xlsx")), "bank")
    for k in ("op_margin", "debt_equity", "roce", "int_cover"):
        assert m.get(k).value is None and m.get(k).note
    assert m.get("roe").value is not None


def test_loss_makers_get_na_not_nonsense(tmp_path):
    c = read_screener(_workbook(tmp_path / "l.xlsx"))
    c.annual.rows["Net profit"][-1] = -5.0
    m = compute(c)
    assert m.get("roe").value is None and "loss" in m.get("roe").note
    assert m.get("np_cagr_3").value is None
