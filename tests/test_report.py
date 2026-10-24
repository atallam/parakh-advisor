import json

from parakh_advisor.advice.snapshot import build_snapshot
from parakh_advisor.cli import main
from parakh_advisor.report.html import inr, lakh, render_snapshot

FIXTURE = "tests/fixtures/holdings_synthetic.json"


def test_indian_number_grouping():
    assert inr(1234567) == "₹12,34,567"
    assert inr(85275) == "₹85,275"
    assert inr(999) == "₹999"
    assert inr(None) == "n/a"
    assert lakh(9225000) == "₹92.25 L"


def test_report_contains_key_sections_and_no_user_ids(portfolio, policy):
    html = render_snapshot(build_snapshot(portfolio, policy))
    for needle in ("Advisory only", "What matters most", "Data health", "TRIM", "cost pending"):
        assert needle in html
    assert "u-fake" not in html  # tenant id must never reach the page


def test_cli_end_to_end(tmp_path, capsys):
    out, js = tmp_path / "p.html", tmp_path / "s.json"
    code = main(["snapshot", "--input", FIXTURE, "--out", str(out), "--json", str(js)])
    assert code == 0 and out.exists()
    assert json.loads(js.read_text())["top3_breach"] is True
    assert "Concentration" in capsys.readouterr().out


def test_cli_reports_errors_without_traceback(tmp_path, capsys):
    code = main(
        ["snapshot", "--input", str(tmp_path / "nope.json"), "--out", str(tmp_path / "x.html")]
    )
    assert code == 2 and "error:" in capsys.readouterr().err


def test_advise_report_says_when_there_are_no_alerts(portfolio, policy):
    snap = build_snapshot(portfolio, policy)
    assert "No changes since the last run" in render_snapshot(snap, alerts=[])
    assert "No changes since the last run" not in render_snapshot(
        snap
    )  # plain snapshot: no state to compare
