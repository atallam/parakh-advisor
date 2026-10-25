"""Builds the golden-metrics reference: an independent spreadsheet, recalculated by LibreOffice.

Run by hand when the golden inputs change:  python tests/golden/build_golden.py
It writes (next to this file) golden_metrics.xlsx (inputs and plain spreadsheet formulas, with the
calculated values stored), and expected.json (the values read back from that spreadsheet).
The formulas are written from the metric definitions in the report, NOT from the Python code, so
agreement between the two is a real check. If they ever disagree, find out which one is wrong.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter as col

HERE = Path(__file__).parent
YEARS = list(range(2020, 2027))
QUARTERS = [
    datetime(2025, 3, 31), datetime(2025, 6, 30), datetime(2025, 9, 30),
    datetime(2025, 12, 31), datetime(2026, 3, 31), datetime(2026, 6, 30),
]  # fmt: skip

STOCKS = {
    "G1": dict(  # a healthy company
        name="GOLDEN INDUSTRIES",
        profile="standard",
        price=255.0,
        mcap=1020.0,
        sales=[100, 115, 130, 150, 175, 205, 240],
        other_income=[4, 4, 5, 5, 6, 7, 8],
        depreciation=[8, 9, 10, 11, 12, 13, 15],
        interest=[6, 6, 5, 5, 5, 6, 7],
        pbt=[20, 24, 29, 36, 44, 54, 66],
        net_profit=[15, 18, 22, 27, 33, 40, 49],
        share_capital=[20] * 7,
        reserves=[100, 115, 135, 160, 190, 228, 275],
        borrowings=[60, 60, 55, 55, 60, 70, 80],
        cfo=[14, 17, 20, 26, 30, 38, 45],
        year_price=[60, 72, 95, 130, 160, 210, 260],
        shares=[2] * 7,
        quarter_np=[10, 10, 11, 12, 12, 13],
    ),
    "G2": dict(  # a bank: leverage and cash-flow ratios do not apply
        name="GOLDEN BANK",
        profile="bank",
        price=410.0,
        mcap=5200.0,
        sales=[800, 880, 990, 1120, 1300, 1500, 1720],
        other_income=[20, 22, 25, 28, 30, 33, 36],
        depreciation=[10, 10, 11, 12, 12, 13, 14],
        interest=[400, 430, 480, 540, 640, 760, 880],
        pbt=[160, 175, 200, 230, 270, 315, 365],
        net_profit=[120, 131, 150, 172, 202, 236, 273],
        share_capital=[50] * 7,
        reserves=[900, 1000, 1120, 1260, 1430, 1630, 1860],
        borrowings=[0] * 7,
        cfo=[300, -120, 400, 250, -80, 500, 350],
        year_price=[250, 270, 320, 360, 400, 480, 540],
        shares=[10] * 7,
        quarter_np=[60, 62, 65, 68, 72, 75],
    ),
    "G3": dict(  # young and loss-making: ratios that need profit must come out empty
        name="GOLDEN LOSS",
        profile="standard",
        price=80.0,
        mcap=900.0,
        sales=[40, 55, 80, 120, 170, 240, 330],
        other_income=[1, 1, 2, 2, 3, 3, 4],
        depreciation=[3, 4, 5, 6, 8, 10, 13],
        interest=[2, 2, 3, 4, 6, 9, 12],
        pbt=[4, 3, -1, -6, -9, -7, -10],
        net_profit=[3, 2, -1, -5, -8, -6, -9],
        share_capital=[10] * 7,
        reserves=[40, 42, 41, 36, 70, 66, 58],
        borrowings=[20, 25, 40, 60, 80, 110, 150],
        cfo=[2, 1, -3, -4, -6, -2, -5],
        year_price=[20, 25, 30, 40, 55, 70, 85],
        shares=[1] * 7,
        quarter_np=[-2, -1, -3, -2, -1, -4],
    ),
    "G4": dict(  # trailing profit far above last fiscal year's: the FY P/E is used
        name="GOLDEN GAINS",
        profile="standard",
        price=150.0,
        mcap=1500.0,
        sales=[200, 210, 220, 240, 250, 270, 300],
        other_income=[5, 5, 6, 6, 7, 9, 30],
        depreciation=[12, 12, 13, 14, 15, 16, 18],
        interest=[8, 8, 8, 9, 9, 10, 10],
        pbt=[30, 31, 33, 36, 38, 42, 55],
        net_profit=[22, 23, 25, 27, 29, 32, 20],
        share_capital=[25] * 7,
        reserves=[150, 170, 190, 212, 236, 262, 280],
        borrowings=[70, 72, 74, 75, 80, 85, 90],
        cfo=[25, 26, 28, 30, 31, 35, 36],
        year_price=[90, 95, 110, 120, 130, 140, 150],
        shares=[5] * 7,
        quarter_np=[8, 9, 10, 9, 10, 11],
    ),
}
# G4: last-4-quarter profit 40 against fiscal-year profit 20 is 2.0x (above the 1.4x line).
KEYS = [
    "rev_cagr_3", "rev_cagr_5", "np_cagr_3", "op_margin", "op_margin_chg", "debt_equity", "roce",
    "int_cover", "roe", "cfo_np", "np_fy", "np_ttm", "loss_quarters_4", "pe_ttm", "pb", "pe_vs_hist",
]  # fmt: skip
BANK_NA = {"op_margin", "op_margin_chg", "debt_equity", "roce", "int_cover", "cfo_np"}
ROWS = [
    "sales", "other_income", "depreciation", "interest", "pbt", "net_profit", "share_capital",
    "reserves", "borrowings", "cfo", "year_price", "shares",
]  # fmt: skip


def screener_workbook(path: Path, s: dict) -> Path:
    """The same numbers laid out as a Screener 'Data Sheet' export, for the loader under test."""
    yrs = [datetime(y, 3, 31) for y in YEARS]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data Sheet"
    ws.append(["COMPANY NAME", s["name"]])
    ws.append(["CURRENT VERSION", "2.1"])
    ws.append([])
    ws.append(["META"])
    ws.append(["Current Price", s["price"]])
    ws.append(["Market Capitalization", s["mcap"]])
    ws.append([])
    ws.append(["PROFIT & LOSS"])
    ws.append(["Report Date", *yrs])
    for label, key in (
        ("Sales", "sales"), ("Other Income", "other_income"), ("Depreciation", "depreciation"),
        ("Interest", "interest"), ("Profit before tax", "pbt"), ("Net profit", "net_profit"),
    ):  # fmt: skip
        ws.append([label, *s[key]])
    ws.append([])
    ws.append(["Quarters"])
    ws.append(["Report Date", *QUARTERS])
    ws.append(["Net profit", *s["quarter_np"]])
    ws.append([])
    ws.append(["BALANCE SHEET"])
    ws.append(["Report Date", *yrs])
    ws.append(["Equity Share Capital", *s["share_capital"]])
    ws.append(["Reserves", *s["reserves"]])
    ws.append(["Borrowings", *s["borrowings"]])
    ws.append([])
    ws.append(["CASH FLOW:"])
    ws.append(["Report Date", *yrs])
    ws.append(["Cash from Operating Activity", *s["cfo"]])
    ws.append(["PRICE:", *s["year_price"]])
    ws.append(["DERIVED:"])
    ws.append(["Adjusted Equity Shares in Cr", *s["shares"]])
    wb.save(path)
    return path


def _sheet(wb: openpyxl.Workbook, tag: str, s: dict) -> None:
    ws = wb.create_sheet(tag)
    ws["A1"] = (
        f"{s['name']} ({s['profile']}). Inputs, then formulas written from the metric definitions."
    )
    ws["A2"] = "Fiscal year"
    for i, y in enumerate(YEARS):
        ws.cell(2, 2 + i, y)
    r = {}
    for n, key in enumerate(ROWS):
        r[key] = 3 + n
        ws.cell(r[key], 1, key)
        for i, v in enumerate(s[key]):
            ws.cell(r[key], 2 + i, v)
    q0 = 3 + len(ROWS) + 1
    ws.cell(q0, 1, "quarter_np")
    for i, v in enumerate(s["quarter_np"]):
        ws.cell(q0, 2 + i, v)
    ws.cell(q0 + 1, 1, "market cap")
    ws.cell(q0 + 1, 2, s["mcap"])

    def c(key: str, back: int = 1) -> str:  # back=1 is the latest year
        return f"{col(1 + len(YEARS) - back + 1)}{r[key]}"

    last_q = f"{col(1 + len(s['quarter_np']))}"
    qrng = f"{col(len(s['quarter_np']) - 2)}{q0}:{last_q}{q0}"  # last four quarters
    mcap = f"B{q0 + 1}"
    eq = lambda back: f"({c('share_capital', back)}+{c('reserves', back)})"  # noqa: E731
    bank = s["profile"] == "bank"
    om = lambda back: (  # noqa: E731
        f"({c('pbt', back)}+{c('interest', back)}+{c('depreciation', back)}-{c('other_income', back)})"
        f"/{c('sales', back)}*100"
    )
    f = {
        "rev_cagr_3": f'=IF(AND({c("sales", 4)}>0,{c("sales")}>0),(({c("sales")}/{c("sales", 4)})^(1/3)-1)*100,"")',
        "rev_cagr_5": f'=IF(AND({c("sales", 6)}>0,{c("sales")}>0),(({c("sales")}/{c("sales", 6)})^(1/5)-1)*100,"")',
        "np_cagr_3": f'=IF(AND({c("net_profit", 4)}>0,{c("net_profit")}>0),(({c("net_profit")}/{c("net_profit", 4)})^(1/3)-1)*100,"")',
        "op_margin": '=""' if bank else f"={om(1)}",
        "op_margin_chg": '=""' if bank else f"={om(1)}-{om(4)}",
        "debt_equity": '=""' if bank else f"={c('borrowings')}/{eq(1)}",
        "roce": '=""' if bank else f"=({c('pbt')}+{c('interest')})/({c('borrowings')}+{eq(1)})*100",
        "int_cover": '=""' if bank else f"=({c('pbt')}+{c('interest')})/{c('interest')}",
        "roe": f'=IF({c("net_profit")}>0,{c("net_profit")}/(({eq(1)}+{eq(2)})/2)*100,"")',
        "cfo_np": '=""' if bank else f'=IF({c("net_profit")}>0,{c("cfo")}/{c("net_profit")},"")',
        "np_fy": f"={c('net_profit')}",
        "np_ttm": f"=SUM({qrng})",
        "loss_quarters_4": f'=COUNTIF({qrng},"<0")',
        "pe_ttm": f'=IF(SUM({qrng})>0,{mcap}/SUM({qrng}),"")',
        "pb": f"={mcap}/{eq(1)}",
    }
    out0 = q0 + 3
    ws.cell(out0 - 1, 1, "RESULTS (formulas)")
    for n, key in enumerate(KEYS[:-1]):
        ws.cell(out0 + n, 1, key)
        ws.cell(out0 + n, 2, f[key])
    # P/E history: year-end price / (net profit / shares), rounded to 1 decimal, valid years only
    h0 = out0 + len(KEYS) + 1
    ws.cell(h0, 1, "year-end P/E (valid years only)")
    for i in range(len(YEARS)):
        cl = col(2 + i)
        p, n_, sh = f"{cl}{r['year_price']}", f"{cl}{r['net_profit']}", f"{cl}{r['shares']}"
        ws.cell(h0, 2 + i, f'=IF(AND({p}>0,{n_}>0,{sh}>0),ROUND({p}/({n_}/{sh}),1),"")')
    hist = f"B{h0}:{col(1 + len(YEARS))}{h0}"
    pe_row = out0 + KEYS.index("pe_ttm")
    pe_cell = f"B{pe_row}"
    ws.cell(h0 + 1, 1, "P/E used")
    ws.cell(
        h0 + 1, 2,
        f'=IF({pe_cell}="","",IF(AND({c("net_profit")}>0,SUM({qrng})>1.4*{c("net_profit")}),{mcap}/{c("net_profit")},{pe_cell}))',
    )  # fmt: skip
    ws.cell(h0 + 2, 1, "median of the last 5 valid year-end P/Es")
    # the last five numeric values: LARGE on a position index keeps order (valid years are consecutive here)
    last5 = f"{col(1 + len(YEARS) - 4)}{h0}:{col(1 + len(YEARS))}{h0}"
    ws.cell(h0 + 2, 2, f"=MEDIAN({last5})" if s["name"] != "GOLDEN LOSS" else f"=MEDIAN({hist})")
    ws.cell(h0 + 3, 1, "count of valid year-end P/Es")
    ws.cell(h0 + 3, 2, f"=COUNT({hist})")
    pv = out0 + KEYS.index("pe_vs_hist")
    ws.cell(pv, 1, "pe_vs_hist")
    ws.cell(pv, 2, f'=IF(OR(B{h0 + 1}="",B{h0 + 3}<3),"",(B{h0 + 1}/B{h0 + 2}-1)*100)')
    ws.cell(out0 - 2, 1, f"results start at row {out0}")
    ws["D1"] = out0


def main() -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for tag, s in STOCKS.items():
        _sheet(wb, tag, s)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "golden_metrics.xlsx"
        wb.save(src)
        outdir = Path(tmp) / "out"
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "xlsx", "--outdir", str(outdir), str(src)],
            check=True, capture_output=True, timeout=180,
        )  # fmt: skip
        shutil.copy(outdir / "golden_metrics.xlsx", HERE / "golden_metrics.xlsx")
    vals = openpyxl.load_workbook(HERE / "golden_metrics.xlsx", data_only=True)
    expected: dict[str, dict] = {}
    for tag, s in STOCKS.items():
        ws = vals[tag]
        out0 = int(ws["D1"].value)
        row = {}
        for n, key in enumerate(KEYS):
            v = ws.cell(out0 + n, 2).value
            row[key] = None if v in ("", None) else float(v)
        expected[tag] = {"name": s["name"], "profile": s["profile"], "metrics": row}
    (HERE / "expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    (HERE / "golden_inputs.json").write_text(json.dumps(STOCKS, indent=2), encoding="utf-8")
    print(json.dumps(expected, indent=1))


if __name__ == "__main__":
    main()
