from parakh_advisor.advice.matrix import decide
from parakh_advisor.advice.snapshot import RiskAction as A
from parakh_advisor.advice.valuation import valuation_stance
from parakh_advisor.alerts.changes import InstrumentState, effective_stance

BASE = dict(weight=4.0, cap=10, buffer=2, dust=0.1, valuation="FAIR", conviction="standard")


def d(**kw):
    return decide(**{**BASE, **kw})


def test_over_cap_trims_whatever_the_thesis_says():
    a = d(weight=16.7, stance="STRONG")
    assert a.action == A.TRIM and "CONCENTRATION" in a.reasons


def test_dust_wins_over_everything_but_is_not_a_sell():
    assert d(weight=0.05, stance="BROKEN").action == A.BUILD_OR_CONSOLIDATE


def test_broken_thesis_means_exit_to_consider():
    assert d(stance="BROKEN").action == A.EXIT


def test_insufficient_or_missing_thesis_is_review_not_a_guess():
    assert d(stance="INSUFFICIENT").action == A.REVIEW
    assert d(stance=None).reasons == ["NO_THESIS_YET"]


def test_weakening_holds_with_no_adds_unless_rich():
    assert d(stance="WEAKENING").action == A.HOLD
    assert d(stance="WEAKENING", valuation="RICH").action == A.TRIM


def test_add_needs_conviction_and_room_below_band():
    assert d(weight=1.5, stance="INTACT").action == A.ADD  # standard band 3-6
    assert d(weight=1.5, stance="INTACT", conviction="tracking").action == A.HOLD
    assert d(weight=4.0, stance="INTACT").action == A.HOLD


def test_rich_and_above_band_trims_toward_target():
    assert d(weight=7.0, stance="INTACT", valuation="STRETCHED").action == A.TRIM


def test_hysteresis_keeps_trim_until_two_points_under_cap():
    assert d(weight=9.0, stance="INTACT", prior_trim_for_concentration=True).action == A.TRIM
    assert d(weight=7.9, stance="INTACT", prior_trim_for_concentration=True).action != A.TRIM


def test_same_inputs_same_label():
    assert d(stance="INTACT") == d(stance="INTACT")


def test_upgrade_needs_two_consecutive_evaluations_downgrade_is_immediate():
    prior = InstrumentState(stance="WEAKENING")
    assert effective_stance(prior, "INTACT") == ("WEAKENING", "INTACT")
    assert effective_stance(
        InstrumentState(stance="WEAKENING", pending_upgrade="INTACT"), "INTACT"
    ) == ("INTACT", None)
    assert effective_stance(InstrumentState(stance="INTACT"), "BROKEN") == ("BROKEN", None)


def test_valuation_bands_and_unreliable_history():
    class M:
        def __init__(self, v):
            self.v = v

        def get(self, k):
            from parakh_advisor.metrics.quality import Metric

            return Metric(key=k, label=k, value=self.v, unit="%", basis="b")

    assert valuation_stance(M(-30))[0] == "CHEAP"
    assert valuation_stance(M(10))[0] == "FAIR"
    assert valuation_stance(M(30))[0] == "RICH"
    assert valuation_stance(M(60))[0] == "STRETCHED"
    assert valuation_stance(M(60), history_reliable=False)[0] == "NA"
    assert valuation_stance(None)[0] == "NA"


def test_downgrade_and_kill_trip_raise_alerts(tmp_path):
    from test_screener_metrics import _workbook
    from test_thesis import NEW

    from parakh_advisor.agents import thesis_analyst
    from parakh_advisor.alerts.changes import detect
    from parakh_advisor.llm.client import FakeLLM
    from parakh_advisor.metrics.quality import compute
    from parakh_advisor.sources.india.screener_export import read_screener

    m = compute(read_screener(_workbook(tmp_path / "a.xlsx")))
    th = thesis_analyst.run(FakeLLM(NEW), "X", "TESTCO", None, m, None)
    prior = InstrumentState(
        stance="INTACT", action="HOLD", thesis_version=1, drivers={"D1": "OK"}, kills={"K1": False}
    )
    kills = [k.model_copy(update={"tripped": True}) for k in th.kill_criteria]
    broken = th.model_copy(update={"kill_criteria": kills})
    sev = {a.severity: a.title for a in detect("TEST", "X", broken, prior, "BROKEN", "EXIT")}
    assert "high" in sev  # broken thesis / kill tripped / EXIT are high severity
    assert (
        detect(
            "TEST",
            "X",
            th,
            InstrumentState(
                stance="INTACT",
                thesis_version=1,
                drivers={d.id: d.status.value for d in th.drivers},
            ),
            "INTACT",
            "HOLD",
        )
        == []
    )


# --- Day 5b: tighter thresholds, baseline summary, notices ---
from parakh_advisor.alerts.changes import Alert, collapse_baseline  # noqa: E402
from parakh_advisor.thesis import rules as _rules  # noqa: E402
from parakh_advisor.thesis.evidence import Evidence as _Ev  # noqa: E402
from parakh_advisor.thesis.models import Driver as _Driver  # noqa: E402


def _ev(key, value):
    import datetime as dt

    return _Ev(
        id=f"MET.{key}@202510",
        kind="metric",
        indicator=key,
        value=value,
        as_of=dt.date(2025, 10, 1),
        text=f"{key}={value}",
        source="test",
    )


def test_tighten_pulls_far_warn_line_in():
    d = _Driver(
        id="D1",
        statement="Margin stays high.",
        kind="metric",
        indicator="op_margin",
        direction="gte",
        warn_threshold=10.0,
        break_threshold=8.0,
    )
    out = _rules.tighten_drivers([d], [_ev("op_margin", 20.0)])[0]
    assert out.warn_threshold == 14.0  # 30% below 20
    assert out.break_threshold <= 14.0 * 0.85 + 0.01 or out.break_threshold == 8.0
    assert "tightened by code" in out.statement


def test_tighten_leaves_close_line_alone():
    d = _Driver(
        id="D1",
        statement="x",
        kind="metric",
        indicator="roe",
        direction="gte",
        warn_threshold=15.0,
    )
    assert _rules.tighten_drivers([d], [_ev("roe", 18.0)])[0].warn_threshold == 15.0


def test_hygiene_adds_low_roe_and_high_pe_and_skips_broker_cash():
    ev = [_ev("roe", 7.0), _ev("pe_ttm", 136.0), _ev("cfo_np", 0.0), _ev("np_fy", 5.0)]
    ids = {d.indicator for d in _rules.hygiene_drivers([], ev, "standard")}
    assert {"roe", "pe_ttm", "cfo_np"} <= ids
    ids_b = {d.indicator for d in _rules.hygiene_drivers([], ev, "broker")}
    assert "cfo_np" not in ids_b and "roe" in ids_b


def test_collapse_baseline_only_when_many():
    mk = lambda s, st: Alert(  # noqa: E731
        severity="low",
        instrument_id=s,
        symbol=s,
        title="New thesis created",
        detail=f"{s}: thesis v1, stance {st}.",
    )
    few = [mk("A", "INTACT"), mk("B", "INTACT")]
    assert collapse_baseline(few) == few
    many = [mk(x, "INTACT") for x in "ABC"] + [mk("D", "WEAKENING")]
    out = collapse_baseline(many)
    assert len(out) == 1 and "INTACT: A, B, C" in out[0].detail


def test_unset_conviction_gives_no_band_advice_but_tracking_does():
    kw = dict(weight=5.0, cap=10.0, buffer=2.0, dust=0.1, stance="INTACT", valuation="RICH")
    assert decide(**kw).action == A.HOLD  # conviction unset: only the concentration cap applies
    assert decide(**kw, conviction="tracking").action == A.TRIM  # you said tracking (0-1%)


# --- Day 8: replay (a second run with the same inputs must be quiet) ---
def _thesis(tmp_path):
    from test_screener_metrics import _workbook
    from test_thesis import NEW

    from parakh_advisor.agents import thesis_analyst
    from parakh_advisor.llm.client import FakeLLM
    from parakh_advisor.metrics.quality import compute
    from parakh_advisor.sources.india.screener_export import read_screener

    m = compute(read_screener(_workbook(tmp_path / "a.xlsx")))
    return thesis_analyst.run(FakeLLM(NEW), "X", "TESTCO", None, m, None)


def _step(th, prior, stance, action, over_pp):
    """One run of the alert logic for one instrument; returns (alerts, new state)."""
    from parakh_advisor.alerts.changes import detect

    eff, pending = effective_stance(prior, stance)
    alerts = detect("T", "X", th, prior, eff, action, over_pp)
    new = InstrumentState(
        stance=eff,
        pending_upgrade=pending,
        action=action,
        thesis_version=th.version,
        drivers={d.id: d.status.value for d in th.drivers},
        kills={k.id: k.tripped for k in th.kill_criteria},
        far_over_cap=over_pp > 5,
    )
    return alerts, new


def test_replay_same_inputs_are_quiet_even_far_over_cap(tmp_path):
    th = _thesis(tmp_path)
    a1, s1 = _step(th, None, "INTACT", "TRIM", 6.7)
    assert [a.title for a in a1] == ["New thesis created"]
    a2, s2 = _step(th, s1, "INTACT", "TRIM", 6.7)
    a3, s3 = _step(th, s2, "INTACT", "TRIM", 6.7)
    assert a2 == [] and a3 == []  # the far-over-cap alert is not repeated every run


def test_replay_alerts_fire_once_on_change(tmp_path):
    th = _thesis(tmp_path)
    _, s = _step(th, None, "INTACT", "HOLD", 0.0)
    a, s = _step(th, s, "INTACT", "HOLD", 7.0)  # crosses 5 points over the cap
    assert [x.title for x in a] == ["Position far above the cap"]
    a, s = _step(th, s, "INTACT", "TRIM", 7.0)
    assert [x.title for x in a] == ["Advice changed: HOLD to TRIM"]
    a, s = _step(th, s, "WEAKENING", "TRIM", 7.0)  # downgrade is immediate
    assert any("downgraded" in x.title for x in a)
    a, s = _step(th, s, "INTACT", "TRIM", 7.0)  # upgrade: first sighting is held back
    assert a == [] and s.stance == "WEAKENING" and s.pending_upgrade == "INTACT"
    a, s = _step(th, s, "INTACT", "TRIM", 7.0)  # second consecutive sighting is accepted
    assert any("upgraded" in x.title for x in a)


def test_digest_text_and_telegram_send(portfolio, policy):
    from parakh_advisor.advice.snapshot import build_snapshot

    snap = build_snapshot(portfolio, policy)
    import json as _json

    import pytest

    from parakh_advisor.notify.telegram import build_digest, send
    from parakh_advisor.sources.http import SourceError

    quiet = build_digest(snap, [])
    assert "No changes since the last run." in quiet and "TODAY'S ADVICE" in quiet
    al = Alert(
        severity="high",
        instrument_id="X",
        symbol="AMD",
        title="Position far above the cap",
        detail="6.7 points",
    )
    loud = build_digest(snap, [al], "out/advice.html")
    assert (
        "ALERTS (1)" in loud
        and "AMD: Position far above the cap" in loud
        and "out/advice.html" in loud
    )
    assert len(build_digest(snap, [al] * 500)) <= 3900

    sent = {}

    def fake_post(url, body):
        sent["url"], sent["body"] = url, body.decode()
        return _json.dumps({"ok": True}).encode()

    send("hello", token="T", chat_id="C", post=fake_post)
    assert "botT/sendMessage" in sent["url"] and "chat_id=C" in sent["body"]
    with pytest.raises(SourceError):
        send("x", token="", chat_id="", post=fake_post)
    with pytest.raises(SourceError):
        send(
            "x",
            token="T",
            chat_id="C",
            post=lambda u, b: _json.dumps({"ok": False, "description": "bad"}).encode(),
        )
