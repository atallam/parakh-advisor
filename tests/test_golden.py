"""Golden checks: the code's metrics against an independent spreadsheet.

tests/golden/golden_metrics.xlsx holds four made-up companies and plain spreadsheet formulas written
from the metric definitions (not from the Python). LibreOffice calculated them and the results are
frozen in expected.json. If the code and the spreadsheet ever disagree, one of them is wrong; find out
which before changing either. To rebuild after changing the inputs: python tests/golden/build_golden.py
"""

import json
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).parent / "golden"))
from build_golden import KEYS, STOCKS, screener_workbook  # noqa: E402

from parakh_advisor.metrics.quality import compute  # noqa: E402
from parakh_advisor.sources.india.screener_export import read_screener  # noqa: E402

GOLDEN = Path(__file__).parent / "golden"
EXPECTED = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("tag", list(STOCKS))
def test_code_matches_the_spreadsheet(tag, tmp_path):
    s = STOCKS[tag]
    m = compute(read_screener(screener_workbook(tmp_path / f"{tag}.xlsx", s)), s["profile"])
    for key in KEYS:
        want = EXPECTED[tag]["metrics"][key]
        metric = m.get(key)
        got = metric.value if metric else None  # banks omit a metric instead of leaving it empty
        if want is None:
            assert got is None, f"{tag} {key}: spreadsheet is empty, code gave {got}"
        else:
            assert got == pytest.approx(want, abs=0.011), f"{tag} {key}: code {got}, sheet {want}"


def test_the_stored_spreadsheet_still_says_what_expected_json_says():
    wb = openpyxl.load_workbook(GOLDEN / "golden_metrics.xlsx", data_only=True)
    for tag in STOCKS:
        ws = wb[tag]
        out0 = int(ws["D1"].value)
        for n, key in enumerate(KEYS):
            v = ws.cell(out0 + n, 2).value
            v = None if v in ("", None) else float(v)
            want = EXPECTED[tag]["metrics"][key]
            assert (v is None) == (want is None) and (v is None or v == pytest.approx(want))


def test_the_cases_cover_what_they_are_meant_to():
    # the fiscal-year P/E rule must actually be exercised, and the loss-maker must stay empty
    g4 = EXPECTED["G4"]["metrics"]
    assert g4["np_ttm"] > 1.4 * g4["np_fy"]
    g3 = EXPECTED["G3"]["metrics"]
    assert g3["pe_ttm"] is None and g3["roe"] is None and g3["np_cagr_3"] is None
    assert EXPECTED["G2"]["metrics"]["debt_equity"] is None  # bank: not applicable
