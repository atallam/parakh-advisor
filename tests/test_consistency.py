"""Perturbation tests: small or irrelevant changes to the inputs must not change the answer.

These check the promise in the design (section 12): a small price move, an irrelevant filing, a different
row order or a re-run does not flip a thesis or an advice label, except exactly at a declared threshold.
"""

import itertools
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "golden"))
from build_golden import STOCKS, screener_workbook  # noqa: E402
from test_screener_metrics import _workbook  # noqa: E402
from test_thesis import NEW  # noqa: E402

from parakh_advisor.advice.matrix import BANDS, decide  # noqa: E402
from parakh_advisor.advice.snapshot import build_snapshot  # noqa: E402
from parakh_advisor.advice.valuation import valuation_stance  # noqa: E402
from parakh_advisor.agents import thesis_analyst  # noqa: E402
from parakh_advisor.ingest.normalise import build_portfolio  # noqa: E402
from parakh_advisor.llm.client import FakeLLM  # noqa: E402
from parakh_advisor.metrics.quality import compute  # noqa: E402
from parakh_advisor.sources.india.screener_export import read_screener  # noqa: E402
from parakh_advisor.thesis.evidence import Evidence, digest, from_metrics  # noqa: E402
from parakh_advisor.thesis.models import ChangeDecision  # noqa: E402

CAP, BUFFER, DUST = 10.0, 2.0, 0.1
STANCES = [None, "INSUFFICIENT", "WEAKENING", "INTACT", "STRONG", "BROKEN"]
VALUATIONS = ["CHEAP", "FAIR", "RICH", "STRETCHED", "NA"]
CONVICTIONS = list(BANDS)
GRID = [round(i * 0.05, 2) for i in range(0, 601)]  # 0.00% to 30.00% of listed equity


def label(weight, stance, valuation, conviction, confidence="MEDIUM", prior_trim=False):
    return decide(
        weight=weight, cap=CAP, buffer=BUFFER, dust=DUST, stance=stance, valuation=valuation,
        conviction=conviction, confidence=confidence, prior_trim_for_concentration=prior_trim,
    ).action  # fmt: skip


COMBOS = list(itertools.product(STANCES, VALUATIONS, CONVICTIONS, ["LOW", "MEDIUM"], [False, True]))


def boundaries(conviction):
    lo, hi = BANDS[conviction]
    return {DUST, lo, hi, CAP, CAP - BUFFER}


@pytest.mark.parametrize("stance", STANCES)
def test_labels_change_only_at_declared_thresholds(stance):
    """Walk the weight axis in 0.05-point steps (a 0.5% price move on a 10% position). Wherever the
    label changes, a documented threshold (dust, a band edge, the cap, cap minus buffer) must lie there."""
    for _, val, conv, conf, prior in (c for c in COMBOS if c[0] == stance):
        labs = [label(w, stance, val, conv, conf, prior) for w in GRID]
        for i in range(len(GRID) - 1):
            w0, w1, a, b = GRID[i], GRID[i + 1], labs[i], labs[i + 1]
            if a != b:
                edges = boundaries(conv)
                assert any(w0 - 1e-9 <= e <= w1 + 1e-9 for e in edges), (
                    f"{stance}/{val}/{conv}/{conf}/prior={prior}: {a} -> {b} between {w0} and {w1}, "
                    f"no threshold there ({sorted(edges)})"
                )


@pytest.mark.parametrize("stance", STANCES)
def test_no_flicker_each_label_is_one_contiguous_run(stance):
    """As weight rises, a label that has been left never comes back (that would be advice flapping)."""
    for _, val, conv, conf, prior in (c for c in COMBOS if c[0] == stance):
        seen, last = set(), None
        for w in GRID:
            a = label(w, stance, val, conv, conf, prior)
            if a != last:
                assert a not in seen, (
                    f"{stance}/{val}/{conv}/{conf}/prior={prior}: {a} returns at {w}"
                )
                seen.add(a)
                last = a


def test_hysteresis_holds_trim_between_cap_minus_buffer_and_cap():
    for w in (8.01, 8.5, 9.0, 9.5, 9.99):
        assert label(w, "INTACT", "FAIR", "core", prior_trim=True).value == "TRIM"
        assert label(w, "INTACT", "FAIR", "core", prior_trim=False).value != "TRIM"
    assert label(7.99, "INTACT", "FAIR", "core", prior_trim=True).value != "TRIM"


def test_label_does_not_depend_on_how_often_it_is_asked():
    first = label(4.2, "INTACT", "CHEAP", "standard")
    assert all(label(4.2, "INTACT", "CHEAP", "standard") == first for _ in range(50))


# ---- valuation: a 1% price move should not move a stock between bands unless it sits on an edge ----
def _stance_at(tag, tmp_path, factor, profile=None):
    s = STOCKS[tag]
    c = read_screener(screener_workbook(tmp_path / f"{tag}_{factor}.xlsx", s))
    c.market_cap *= factor
    return valuation_stance(compute(c, s["profile"]))[0]


@pytest.mark.parametrize("tag", list(STOCKS))
def test_one_percent_price_move_keeps_the_valuation_band(tag, tmp_path):
    base = _stance_at(tag, tmp_path, 1.0)
    for f in (0.99, 1.01, 0.98, 1.02):
        assert _stance_at(tag, tmp_path, f) == base, f"{tag} flipped at {f:.2f}x market cap"


def test_valuation_flips_exactly_at_the_band_edge(tmp_path):
    # G2 sits at -8.5% against its own history (FAIR). Market cap x1.3115 reaches +20%, the FAIR/RICH edge.
    s = STOCKS["G2"]
    c = read_screener(screener_workbook(tmp_path / "g2.xlsx", s))
    stances = {}
    for f in (1.30, 1.33):
        c2 = read_screener(screener_workbook(tmp_path / f"g2_{f}.xlsx", s))
        c2.market_cap *= f
        stances[f] = valuation_stance(compute(c2, s["profile"]))[0]
    assert stances == {1.30: "FAIR", 1.33: "RICH"}
    assert c.market_cap > 0


# ---- thesis: an irrelevant filing or a small price move does not rewrite the thesis ----
@pytest.fixture
def healthy(tmp_path):
    m = compute(read_screener(_workbook(tmp_path / "a.xlsx")))
    return m.model_copy(update={"quarters_reported": 12})  # enough history to be judged


@pytest.fixture
def reaffirm():
    easy = [{**NEW["drivers"][0], "warn_threshold": 10, "break_threshold": 5}, *NEW["drivers"][1:]]
    return {**NEW, "drivers": easy}


def _signature(t):
    return (
        t.stance,
        t.why_own,
        [(d.id, d.status, d.warn_threshold, d.break_threshold) for d in t.drivers],
        [(k.id, k.tripped) for k in t.kill_criteria],
    )


def test_irrelevant_new_filing_does_not_change_the_thesis(healthy, reaffirm):
    prior = thesis_analyst.run(FakeLLM(reaffirm), "X", "TESTCO", None, healthy, None)
    junk = Evidence(
        id="DOC.X.abc12345.p1", kind="filing", source="notice.txt",
        text="Notice of the annual general meeting and the appointment of scrutinisers.",
        as_of=date(2026, 7, 1),
    )  # fmt: skip
    again = thesis_analyst.run(
        FakeLLM({**reaffirm, "decision": "REAFFIRM"}), "X", "TESTCO", None, healthy, prior, [junk]
    )
    assert again.change_decision == ChangeDecision.REAFFIRM and not again.rejected_changes
    assert _signature(again) == _signature(prior)


def test_one_percent_price_move_does_not_change_the_thesis(healthy, reaffirm, tmp_path):
    prior = thesis_analyst.run(FakeLLM(reaffirm), "X", "TESTCO", None, healthy, None)
    c = read_screener(_workbook(tmp_path / "b.xlsx"))
    c.market_cap *= 1.01
    moved = compute(c).model_copy(update={"quarters_reported": 12})
    again = thesis_analyst.run(
        FakeLLM({**reaffirm, "decision": "REAFFIRM"}), "X", "TESTCO", None, moved, prior
    )
    assert _signature(again) == _signature(prior)


def test_unchanged_inputs_give_an_identical_thesis_and_digest(healthy, reaffirm):
    a = thesis_analyst.run(FakeLLM(reaffirm), "X", "TESTCO", None, healthy, None)
    b = thesis_analyst.run(FakeLLM(reaffirm), "X", "TESTCO", None, healthy, None)
    assert _signature(a) == _signature(b) and a.inputs_digest == b.inputs_digest


def test_evidence_order_does_not_change_the_digest(healthy):
    ev = from_metrics(healthy)
    assert digest(ev) == digest(list(reversed(ev)))


def test_a_stale_filing_cannot_lift_confidence(healthy, reaffirm):
    old = Evidence(
        id="DOC.X.old00001.p1", kind="filing", source="old.txt",
        text="Management discussion from a call long ago.", as_of=date(2024, 1, 15),
    )  # fmt: skip
    t = thesis_analyst.run(FakeLLM(reaffirm), "X", "TESTCO", None, healthy, None, [old])
    assert t.confidence.value == "LOW"
    fresh = old.model_copy(
        update={"id": "DOC.X.new00001.p1", "as_of": date.today() - timedelta(days=30)}
    )
    # a fresh filing is dated after the metrics' own date in this fixture, so it counts
    t2 = thesis_analyst.run(FakeLLM(reaffirm), "X", "TESTCO", None, healthy, None, [fresh])
    assert t2.confidence.value in {"MEDIUM", "HIGH"}


# ---- snapshot: row order and a uniform price move do not change weights or labels ----
def _weights(snap):
    return {h.instrument_id: (h.weight_pct, h.action) for h in snap.holdings}


def test_row_order_does_not_change_weights_or_actions(rows, policy):
    a = _weights(build_snapshot(build_portfolio(rows), policy))
    b = _weights(build_snapshot(build_portfolio(list(reversed(rows))), policy))
    assert a == b


def test_every_price_up_one_percent_changes_no_weight_or_action(rows, policy):
    base = build_snapshot(build_portfolio(rows), policy)
    scaled = []
    for r in rows:
        r = dict(r)
        if isinstance(r.get("current_price"), (int, float)):
            r["current_price"] = r["current_price"] * 1.01
        scaled.append(r)
    moved = build_snapshot(build_portfolio(scaled), policy)
    for iid, (w, act) in _weights(base).items():
        w2, act2 = _weights(moved)[iid]
        assert act == act2
        if w is not None:
            assert w2 == pytest.approx(w, abs=0.02)
