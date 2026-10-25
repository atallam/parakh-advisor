"""EDGAR filing text: finding the EX-99.1 exhibit and the MD&A section across different layouts."""

import json

from parakh_advisor.sources.text import extract_section
from parakh_advisor.sources.us.filings import EdgarFilings, _mda_patterns

INDEX_PAGE = b"""
<a href="/cgi-bin/browse-edgar?action=getcompany">Company</a><a href="/index.htm">Home</a>
<table class="tableFile">
<tr><td>1</td><td>8-K</td><td><a href="/ix?doc=/Archives/edgar/data/2/000000000226000121/amd-20260804.htm">amd-20260804.htm</a></td><td>8-K</td><td>30308</td></tr>
<tr><td>2</td><td>EX-99.1</td><td><a href="/Archives/edgar/data/2/000000000226000121/q22026991.htm">q22026991.htm</a></td><td>EX-99.1</td><td>448891</td></tr>
<tr><td>3</td><td>EX-99.2</td><td><a href="/Archives/edgar/data/2/000000000226000121/slides.htm">slides.htm</a></td><td>EX-99.2</td><td>35590</td></tr>
</table>"""


def test_exhibit_is_found_by_type_not_file_name(tmp_path):
    def fetch(url: str) -> bytes:
        if url.endswith("-index.html"):
            return INDEX_PAGE
        raise AssertionError(f"unexpected fetch {url}")

    f = EdgarFilings.__new__(EdgarFilings)
    f.fetch = fetch
    assert f._exhibit_name(2, "000000000226000121", "0000000002-26-000121") == "q22026991.htm"


def test_exhibit_falls_back_to_file_name_when_index_page_is_unavailable():
    from parakh_advisor.sources.http import SourceError

    def fetch(url: str) -> bytes:
        if url.endswith("-index.html"):
            raise SourceError("refused")
        return json.dumps(
            {"directory": {"item": [{"name": "ex99-1.htm"}, {"name": "a.jpg"}]}}
        ).encode()

    f = EdgarFilings.__new__(EdgarFilings)
    f.fetch = fetch
    assert f._exhibit_name(2, "x", "y") == "ex99-1.htm"


def test_mda_heading_with_table_bars_and_curly_apostrophe():
    body = "Revenue grew and margins improved this quarter. " * 120
    text = (
        "Item 2 | Management’s Discussion and Analysis of Financial Condition | 22\n"
        "Item 3 | Quantitative and Qualitative Disclosures | 40\n"
        "ITEM 2. | MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION\n\n"
        + body
        + "\nITEM 3. | QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK\nother"
    )
    start, end = _mda_patterns("10-Q")
    got = extract_section(text, start, end)
    assert got.startswith("ITEM 2.") and "Revenue grew" in got and "market risk" not in got.lower()
