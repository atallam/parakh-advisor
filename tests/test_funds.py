from datetime import date, timedelta

from parakh_advisor.funds.health import (
    FundHealth,
    NavSource,
    _base_tokens,
    assess,
    benchmark_key,
    cagr,
    category_overlap,
    vol_and_drawdown,
)


def series(daily_growth: float, days: int = 2200, end=date(2026, 10, 20), start_nav=100.0):
    out, v = [], start_nav
    d0 = end - timedelta(days=days)
    for i in range(days + 1):
        out.append((d0 + timedelta(days=i), v))
        v *= 1 + daily_growth
    return out


class FakeNav(NavSource):
    def __init__(self, data):
        self.data, self.pause = data, 0

    def nav(self, code, max_age_days=1):
        from parakh_advisor.sources.http import SourceError

        if code not in self.data:
            raise SourceError("none")
        return self.data[code]

    def direct_twin(self, code, name):
        return "D" if "D" in self.data else None


END = date(2026, 10, 20)


def test_cagr_matches_known_growth():
    s = series(0.0003)  # (1.0003)**365.25 - 1 ~ 11.6% a year
    assert abs(cagr(s, 3, END) - 11.57) < 0.3
    assert cagr(series(0.0003, days=100), 3, END) is None


def test_hit_rate_and_status_healthy_vs_lagging():
    bench = series(0.0003)
    nav = FakeNav({"B": bench, "148519": bench, "147625": bench})
    good = series(0.0004)
    nav.data["good"] = good
    h = assess(
        "good", "Good Fund - Direct Plan - Growth", "Equity Scheme - Flexi Cap Fund", "Direct", nav
    )
    assert h.status == "HEALTHY" and h.excess3 > 0 and h.hit_rate == 1.0
    nav.data["bad"] = series(-0.0002)
    h = assess("bad", "Bad Fund", "Equity Scheme - Small Cap Fund", "Direct", nav)
    assert h.status == "LAGGING" and h.excess3 < -3
    nav.data["mid"] = series(0.00027)
    assert (
        assess("mid", "Mid Fund", "Equity Scheme - Flexi Cap Fund", "Direct", nav).status == "WATCH"
    )


def test_too_new_and_no_data():
    nav = FakeNav({"147625": series(0.0003), "new": series(0.0005, days=300)})
    assert assess("new", "New", "Flexi Cap", "Direct", nav).status == "TOO_NEW"
    assert assess("missing", "X", "Flexi Cap", "Direct", nav).status == "NO_DATA"


def test_regular_plan_gap_measured_against_direct_twin():
    nav = FakeNav({"147625": series(0.0003), "R": series(0.00035), "D": series(0.00040)})
    h = assess(
        "R", "X Fund - Regular Plan - Growth", "Equity Scheme - Flexi Cap Fund", "Regular", nav
    )
    assert h.direct_gap is not None and h.direct_gap > 0.3
    assert any("Direct plan returned" in line for line in h.lines)


def test_vol_drawdown_and_helpers():
    s = series(0.0)
    vol, dd = vol_and_drawdown(s, END)
    assert vol == 0 and dd == 0
    assert benchmark_key("Equity Schemes - Small Cap Fund") == "smallcap"
    assert benchmark_key("Equity Scheme - Contra Fund") == "broad"
    assert _base_tokens(
        "Nippon India Small Cap Fund - Regular Plan - Growth Option"
    ) == _base_tokens("Nippon India Small Cap Fund - Direct Plan - Growth")


def test_category_overlap_only_two_or_more():
    rows = [
        ("A", "Small Cap Fund", 100.0),
        ("B", "Small Cap Fund", 50.0),
        ("C", "Flexi Cap Fund", 80.0),
    ]
    o = category_overlap(rows, 1000.0)
    assert len(o) == 1 and o[0].category == "Small Cap Fund" and abs(o[0].pct - 15.0) < 1e-9
    assert FundHealth(scheme_code="x", status="HEALTHY").lines == []


def _xlsx(path, header_row, rows, pre=()):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in pre:
        ws.append(r)
    ws.append(header_row)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def test_read_fund_file_finds_header_and_handles_percent_or_fraction(tmp_path):
    from parakh_advisor.funds.lookthrough import read_fund_file

    p = _xlsx(
        tmp_path / "ppfas.xlsx",
        ["Name of the Instrument", "ISIN", "Industry", "Quantity", "% to Net Assets"],
        [
            ["HDFC Bank Ltd", "INE040A01034", "Banks", 100, 8.1],
            ["Alphabet Inc A", "US02079K3059", "Tech", 10, 5.2],
            ["Total", None, None, None, 13.3],
        ],
        pre=[["Scheme X portfolio as on 30 Sep 2026"], []],
    )
    f = read_fund_file(p)
    assert [(i, round(pc, 1)) for i, _, pc in f.rows] == [
        ("INE040A01034", 8.1),
        ("US02079K3059", 5.2),
    ]
    p2 = _xlsx(
        tmp_path / "frac.xlsx",
        ["Instrument", "% of NAV"],
        [["Meta Platforms Inc", 0.05], ["Tesla Inc", 0.03]],
    )
    assert round(read_fund_file(p2).rows[0][2], 1) == 5.0


def test_read_fund_file_clear_error_when_no_header(tmp_path):
    import pytest

    from parakh_advisor.funds.lookthrough import read_fund_file

    p = _xlsx(tmp_path / "bad.xlsx", ["foo", "bar"], [["a", 1]])
    with pytest.raises(ValueError, match="no header row"):
        read_fund_file(p)


def test_match_files_to_funds_by_words(tmp_path):
    from parakh_advisor.funds.lookthrough import match_labels_to_funds

    a, b = "Parag_Parikh_Flexi_Cap_Sep", "random"
    m = match_labels_to_funds(
        [a, b],
        {
            "F1": "Parag Parikh Flexi Cap Fund - Regular Plan - Growth",
            "F2": "Invesco India Small Cap Fund",
        },
    )
    assert m == {"F1": a}


def test_look_through_exposure_abroad_and_pair_overlap():
    from parakh_advisor.funds.lookthrough import FundFile, look_through

    direct = {
        "US:GOOGL": ("Alphabet Inc. Class A Common Stock", 700.0),
        "INE040A01034": ("HDFC BANK LIMITED", 100.0),
    }
    funds = {"FA": ("Fund A", 1000.0), "FB": ("Fund B", 500.0)}
    files = {
        "FA": FundFile(
            "a", [("US02079K3059", "Alphabet Inc A", 5.0), ("INE040A01034", "HDFC Bank Ltd", 8.0)]
        ),
        "FB": FundFile("b", [("INE040A01034", "HDFC Bank Ltd", 6.0), ("INE999", "Other", 10.0)]),
    }
    exp, abroad, pairs = look_through(direct, funds, files)
    g = next(e for e in exp if e.name.startswith("Alphabet"))
    assert g.via_funds_inr == 50.0 and g.direct_inr == 700.0
    h = next(e for e in exp if e.name.startswith("HDFC"))
    assert h.via_funds_inr == 80.0 + 30.0
    assert abroad == 50.0
    assert pairs[0][2] == 6.0  # min(8, 6) on the shared HDFC Bank weight


def test_factsheet_lines_split_equity_overseas_and_skip_debt():
    from parakh_advisor.funds.lookthrough import OVERSEAS_ISIN, FundFile, parse_factsheet_lines

    left = [
        "Portfolio Data",
        "Core Equity",
        "Name % of Net Assets",
        "HDFC Bank Limited 7.75%",
        "Sub Total 72.06%",
        "@Arbitrage and Special Situations 1.44%",
        "Total 73.50%",
        "Overseas Securities, IDRs and ADRs",
        "Alphabet Inc A 4.29%",
        "Total 11.90%",
        "Units issued by REITs & InvITs",
        "Embassy Office Parks REIT 2.49%",
        "Total 6.27%",
        "Debt and Money Market Instruments",
        "Certificate of Deposit",
        "Canara Bank (18/12/2026) 0.31%",
    ]
    ff = FundFile("x")
    section = parse_factsheet_lines(left, "", ff)
    assert section == "other"
    assert ff.rows == [
        ("", "HDFC Bank Limited", 7.75),
        (OVERSEAS_ISIN, "Alphabet Inc A", 4.29),
        ("", "Embassy Office Parks REIT", 2.49),
    ]
    # a debt page continues in the right-hand column: stays out of the holdings
    parse_factsheet_lines(["Kotak Mahindra Bank Limited (08/01/2027) 0.14%"], section, ff)
    assert len(ff.rows) == 3


def test_index_fund_file_with_market_value_header_and_self_row(tmp_path):
    from parakh_advisor.funds.lookthrough import read_fund_file

    p = _xlsx(
        tmp_path / "idx.xlsx",
        ["Security Description", "ISIN", "Market Value %"],
        [
            ["JBN50", None, 100],
            ["HDFC BANK", "INE040A01034", 10.15],
            ["CASH", None, -0.2],
            ["INR CASH(Corp Act)", None, 0.01],
        ],
    )
    f = read_fund_file(p)
    assert f.rows == [("INE040A01034", "HDFC BANK", 10.15)]


def test_scheme_title_is_read_from_rows_above_the_header(tmp_path):
    from parakh_advisor.funds.lookthrough import read_fund_file

    p = _xlsx(
        tmp_path / "opaque-name.xlsx",
        [None, "Name of the Instrument ", "ISIN", "Quantity", "% to NAV"],
        [
            [None, "HDFC Bank Ltd", "INE040A01034", 10, 5.9],
            [None, "Net Receivables / (Payables)", None, 0, -1.2],
        ],
        pre=[
            [None, "JioBlackRock Flexi Cap Fund"],
            [None, "Monthly Portfolio Statement as on September 30, 2026"],
        ],
    )
    f = read_fund_file(p)
    assert f.title == "JioBlackRock Flexi Cap Fund"
    assert [r[1] for r in f.rows] == ["HDFC Bank Ltd"]
