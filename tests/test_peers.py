"""Sector percentiles from named peer groups."""

import pytest
from test_screener_metrics import _workbook

from parakh_advisor.agents import thesis_analyst
from parakh_advisor.llm.client import FakeLLM
from parakh_advisor.metrics import peers as P
from parakh_advisor.metrics.quality import CompanyMetrics, Metric, compute
from parakh_advisor.sources.india.screener_export import read_screener
from parakh_advisor.sources.peers import PeerGroup, PeerLoader, load_peer_groups


def test_rank_counts_wins_and_halves_ties():
    assert P.rank(10, [1, 2, 3, 4]) == 100
    assert P.rank(0, [1, 2, 3, 4]) == 0
    assert P.rank(2.5, [1, 2, 3, 4]) == 50
    assert P.rank(2, [2, 2]) == 50  # all ties
    assert P.rank(10, [1, 2, 3, 4], higher_is_better=False) == 0  # high debt is worst
    with pytest.raises(ValueError):
        P.rank(1, [])


def _cm(name="X", profile="standard", **vals):
    ms = [Metric(key=k, label=k, value=v, unit="x", basis="b") for k, v in vals.items()]
    return CompanyMetrics(
        name=name,
        profile=profile,
        fy_end=None,
        quarter_end=None,
        price=None,
        market_cap_cr=None,
        metrics=ms,
    )


def _peers(n=6):
    return [
        _cm(
            f"P{i}",
            rev_cagr_3=i,
            roce=i * 2,
            op_margin=i * 3,
            debt_equity=i / 10,
            cfo_np=i / 5,
            pe_ttm=10 + i,
        )
        for i in range(1, n + 1)
    ]


def test_best_in_cohort_is_top_third_and_worst_is_not():
    best = _cm(rev_cagr_3=99, roce=99, op_margin=99, debt_equity=0.0, cfo_np=9, pe_ttm=200)
    ctx = P.sector_context("g", best, _peers())
    assert ctx.quality_pct == 100 and ctx.top_third and ctx.pe_pct == 100 and ctx.peers == 6
    worst = _cm(rev_cagr_3=-9, roce=-9, op_margin=-9, debt_equity=9, cfo_np=-1, pe_ttm=1)
    ctx = P.sector_context("g", worst, _peers())
    assert ctx.quality_pct == 0 and not ctx.top_third and ctx.pe_pct == 0


def test_leverage_counts_in_the_right_direction():
    low = P.sector_context(
        "g", _cm(rev_cagr_3=3, roce=6, op_margin=9, debt_equity=0.0, cfo_np=0.6), _peers()
    )
    assert low.dims["debt_equity"] == 100


def test_too_few_peers_gives_no_percentile_with_reason():
    ctx = P.sector_context("g", _cm(rev_cagr_3=1), _peers(4))
    assert ctx.quality_pct is None and "need" in ctx.note and not ctx.top_third


def test_too_few_measures_gives_no_percentile():
    ctx = P.sector_context("g", _cm(rev_cagr_3=5, roce=5), _peers())
    assert ctx.quality_pct is None and "need 3" in ctx.note


def test_missing_peer_values_are_skipped_not_zeroed():
    peers = _peers()
    for p in peers[:3]:  # three peers have no cfo_np: still 3 values, below MIN_PEERS
        p.metrics = [m for m in p.metrics if m.key != "cfo_np"]
    ctx = P.sector_context(
        "g", _cm(rev_cagr_3=3, roce=6, op_margin=9, debt_equity=0.3, cfo_np=0.6), peers
    )
    assert "cfo_np" not in ctx.dims and len(ctx.dims) == 4


def test_bank_group_uses_bank_measures():
    peers = [_cm(f"B{i}", "bank", rev_cagr_3=i, np_cagr_3=i, roe=i) for i in range(1, 7)]
    ctx = P.sector_context(
        "banks", _cm(profile="bank", rev_cagr_3=9, np_cagr_3=9, roe=9), peers, "bank"
    )
    assert set(ctx.dims) == {"rev_cagr_3", "np_cagr_3", "roe"} and ctx.quality_pct == 100


def test_evidence_states_cohort_and_size_and_gap(tmp_path):
    from datetime import date

    ctx = P.sector_context(
        "semis",
        _cm(rev_cagr_3=9, roce=9, op_margin=99, debt_equity=0, cfo_np=9, pe_ttm=3),
        _peers(),
    )
    ev = P.to_evidence(ctx, date(2026, 9, 30))
    assert (
        ev[0].id == "MET.sector_quality_pct@202609"
        and "semis" in ev[0].text
        and "6 peers" in ev[0].text
    )
    na = P.to_evidence(P.sector_context("semis", _cm(), _peers(2)), date(2026, 9, 30))
    assert na[0].value is None and "n/a" in na[0].text


def test_thesis_carries_percentile_evidence_and_passes_top_third(tmp_path, monkeypatch):
    from test_thesis import NEW

    from parakh_advisor.thesis import rules

    m = compute(read_screener(_workbook(tmp_path / "a.xlsx")))
    seen = {}
    real = rules.derive_stance

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)

    monkeypatch.setattr(rules, "derive_stance", spy)
    top = P.SectorContext(group="g", peers=6, quality_pct=80.0, dims={"roce": 80.0})
    t = thesis_analyst.run(FakeLLM(NEW), "X", "T", None, m, None, None, top)
    assert seen["top_third"] is True
    plain = thesis_analyst.run(FakeLLM(NEW), "X", "T", None, m, None, None, None)
    assert t.inputs_digest != plain.inputs_digest  # percentiles are part of the inputs


def test_strong_needs_top_third():
    from parakh_advisor.thesis.models import Confidence, Driver, DriverStatus, Stance
    from parakh_advisor.thesis.rules import derive_stance

    ok = [
        Driver(id=f"D{i}", statement="s", kind="metric", status=DriverStatus.OK) for i in range(3)
    ]
    assert derive_stance(ok, [], 12, top_third=True, sourced=True) == (
        Stance.STRONG,
        Confidence.MEDIUM,
    )
    assert derive_stance(ok, [], 12, top_third=False, sourced=True)[0] == Stance.INTACT


def test_india_group_loads_exports_and_excludes_the_holding(tmp_path):
    d = tmp_path / "peers"
    d.mkdir()
    for i in range(7):
        _workbook(d / f"{i}.xlsx", name=f"PEER {i} LTD")
    loader = PeerLoader({"auto": PeerGroup(market="IN", dir=str(d))})
    assert len(loader.peers_of("auto", set())) == 7
    assert len(loader.peers_of("auto", {"peer 3 ltd"})) == 6  # case-insensitive exclusion


def test_missing_folder_and_unknown_group_are_reported_not_fatal(tmp_path, capsys):
    loader = PeerLoader({"auto": PeerGroup(market="IN", dir=str(tmp_path / "nope"))})
    assert loader.peers_of("auto", set()) == [] and loader.peers_of("ghost", set()) == []
    err = capsys.readouterr().err
    assert "not found" in err and "not defined" in err


def test_config_file_loads(tmp_path):
    f = tmp_path / "peers.yaml"
    f.write_text("semis: {market: US, members: [AVGO, QCOM]}\n", encoding="utf-8")
    g = load_peer_groups(f)
    assert g["semis"].members == ["AVGO", "QCOM"] and load_peer_groups(tmp_path / "none.yaml") == {}


def test_yaml_yes_no_tickers_are_caught_with_a_clear_message(tmp_path):
    f = tmp_path / "peers.yaml"
    f.write_text("semis: {market: US, members: [AVGO, ON]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="quotes"):
        load_peer_groups(f)


def test_shipped_peer_config_and_instruments_agree():
    from parakh_advisor.ingest.instruments import load_instruments

    groups = load_peer_groups("config/peers.yaml")
    used = {
        i.peer_group for i in load_instruments("config/instruments.yaml").values() if i.peer_group
    }
    assert used and used <= set(groups)
    for g in groups.values():
        assert len(set(g.members)) == len(g.members)  # no duplicates
