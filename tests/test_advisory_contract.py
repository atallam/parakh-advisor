"""advisory.v1: the contract WealthLens will read. A change here must be deliberate."""

import json
from pathlib import Path

import pytest
from test_screener_metrics import _workbook
from test_thesis import NEW

from parakh_advisor.advice.apply import apply_advice
from parakh_advisor.advice.snapshot import build_snapshot
from parakh_advisor.agents import thesis_analyst
from parakh_advisor.contracts.advisory_v1 import CONFLICT, TABLES, build_bundle
from parakh_advisor.contracts.holdings_v2 import DIRECT_STOCKS
from parakh_advisor.ingest.instruments import Instrument
from parakh_advisor.llm.client import FakeLLM
from parakh_advisor.metrics.quality import compute
from parakh_advisor.publish.supabase import publish
from parakh_advisor.sources.http import SourceError
from parakh_advisor.sources.india.screener_export import read_screener

GOLDEN = Path(__file__).parent / "fixtures" / "advisory_v1_shape.json"
USER = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def run_inputs(portfolio, policy, tmp_path):
    snap = build_snapshot(portfolio, policy)
    ids = [h.instrument_id for h in snap.holdings if h.asset_class in DIRECT_STOCKS][:2]
    m = compute(read_screener(_workbook(tmp_path / "a.xlsx")))
    theses = {i: thesis_analyst.run(FakeLLM(NEW), i, "TESTCO", None, m, None) for i in ids}
    metrics = {i: m for i in ids}
    inst = {i: Instrument(symbol=f"S{n}", conviction="core") for n, i in enumerate(ids)}
    alerts, _ = apply_advice(snap, policy, theses, metrics, inst, {})
    return snap, alerts, theses, metrics, policy, inst


def _bundle(run_inputs):
    snap, alerts, theses, metrics, policy, inst = run_inputs
    return build_bundle(
        snap, alerts, theses, metrics, policy, USER, {k: v.symbol for k, v in inst.items()}
    )


def _shape(b):
    """Table -> sorted column names and type names of the first row: the contract's shape."""
    out = {}
    for t in TABLES:
        rows = b.rows(t)
        if rows:
            out[t] = {k: type(v).__name__ for k, v in sorted(rows[0].items())}
    return out


def test_shape_matches_the_frozen_contract(run_inputs):
    shape = _shape(_bundle(run_inputs))
    if not GOLDEN.exists():  # first run only: write it, then it is frozen in git
        GOLDEN.write_text(json.dumps(shape, indent=2, sort_keys=True), encoding="utf-8")
    frozen = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for table, cols in frozen.items():
        got = shape.get(table, {})
        # NoneType is allowed where the frozen sample had a value, and the reverse (optional columns)
        for col, typ in cols.items():
            assert col in got, f"{table}.{col} was removed: bump the contract version"
            assert got[col] == typ or "NoneType" in (got[col], typ), (
                f"{table}.{col}: {typ} became {got[col]}"
            )
        assert set(got) <= set(cols), (
            f"{table} gained columns {set(got) - set(cols)}: bump the version"
        )


def test_every_row_belongs_to_the_user_and_ids_are_unique(run_inputs):
    b = _bundle(run_inputs)
    for t in TABLES:
        rows = b.rows(t)
        assert all(r.get("user_id") == USER for r in rows if t != "advisory_evidence"), t
        key = CONFLICT[t].split(",")
        keys = [tuple(r[k] for k in key) for r in rows]
        assert len(keys) == len(set(keys)), f"duplicate keys in {t}"


def test_drivers_point_at_their_thesis_and_runs_are_the_commit_marker(run_inputs):
    b = _bundle(run_inputs)
    thesis_ids = {r.id for r in b.advisory_theses}
    assert b.advisory_drivers and all(d.thesis_id in thesis_ids for d in b.advisory_drivers)
    assert TABLES[-1] == "advisory_runs" and len(b.advisory_runs) == 1
    run_id = b.advisory_runs[0].id
    assert all(a.run_id == run_id for a in b.advisory_actions)
    assert b.advisory_portfolio[0].run_id == run_id


def test_same_inputs_give_the_same_ids_so_republishing_is_a_no_op(run_inputs):
    a, b = _bundle(run_inputs), _bundle(run_inputs)
    assert a.advisory_runs[0].id == b.advisory_runs[0].id
    assert [x.id for x in a.advisory_actions] == [x.id for x in b.advisory_actions]
    assert [x.id for x in a.advisory_theses] == [x.id for x in b.advisory_theses]


def test_a_different_user_gets_different_ids(run_inputs):
    snap, alerts, theses, metrics, policy, _ = run_inputs
    other = build_bundle(
        snap, alerts, theses, metrics, policy, "22222222-2222-2222-2222-222222222222"
    )
    assert other.advisory_runs[0].id != _bundle(run_inputs).advisory_runs[0].id


def test_a_changed_action_makes_a_new_run(run_inputs):
    snap, alerts, theses, metrics, policy, inst = run_inputs
    before = _bundle(run_inputs).advisory_runs[0].id
    h = next(h for h in snap.holdings if h.action)
    h.stance = "BROKEN"
    assert _bundle(run_inputs).advisory_runs[0].id != before


def test_action_rows_carry_the_band_for_the_conviction(run_inputs):
    b = _bundle(run_inputs)
    mine = {r.instrument_id for r in b.advisory_theses}
    core = [a for a in b.advisory_actions if a.instrument_id in mine]
    assert core and all((a.band_low, a.band_high) == (6.0, 10.0) for a in core)


def test_thesis_body_round_trips_to_a_thesis(run_inputs):
    from parakh_advisor.thesis.models import Thesis

    b = _bundle(run_inputs)
    t = Thesis.model_validate(b.advisory_theses[0].body)
    assert t.version == b.advisory_theses[0].version


def test_nothing_secret_leaves_in_the_rows(run_inputs, monkeypatch):
    monkeypatch.setenv("SUPABASE_KEY", "sekret-key-123")
    text = _bundle(run_inputs).model_dump_json()
    assert "sekret-key-123" not in text


class Recorder:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, url, body, headers):
        if self.fail_on and self.fail_on in url:
            raise SourceError("boom")
        self.calls.append((url, json.loads(body), headers))
        return b""


def test_publish_writes_every_table_runs_last_and_never_updates(run_inputs):
    rec = Recorder()
    sent = publish(_bundle(run_inputs), "https://x.supabase.co/", "k", post=rec)
    order = [c[0].split("/rest/v1/")[1].split("?")[0] for c in rec.calls]
    assert order[-1] == "advisory_runs" and set(sent) == set(TABLES)
    assert all("ignore-duplicates" in c[2]["Prefer"] for c in rec.calls)  # insert-only
    assert all("on_conflict=" in c[0] for c in rec.calls)
    assert all(c[2]["Authorization"] == "Bearer k" for c in rec.calls)


def test_a_failed_write_stops_before_the_run_marker(run_inputs):
    rec = Recorder(fail_on="advisory_alerts")
    with pytest.raises(SourceError):
        publish(_bundle(run_inputs), "https://x.supabase.co", "k", post=rec)
    assert not any(
        "advisory_runs" in c[0] for c in rec.calls
    )  # no marker, so the tab shows nothing


def test_publish_needs_credentials(run_inputs, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    with pytest.raises(SourceError, match="SUPABASE_URL"):
        publish(_bundle(run_inputs), post=Recorder())


def test_large_tables_are_sent_in_chunks(run_inputs):
    b = _bundle(run_inputs)
    b.advisory_evidence = [{"id": f"e{i}", "user_id": USER} for i in range(450)]
    rec = Recorder()
    publish(b, "https://x.supabase.co", "k", post=rec)
    ev = [c for c in rec.calls if "advisory_evidence" in c[0]]
    assert [len(c[1]) for c in ev] == [200, 200, 50]


def test_sql_file_defines_every_table_with_row_level_security():
    sql = (Path(__file__).parent.parent / "supabase" / "advisory_v1.sql").read_text(
        encoding="utf-8"
    )
    for t in TABLES:
        assert f"create table if not exists {t}" in sql and f"'{t}'" in sql
    assert "enable row level security" in sql and "auth.uid() = user_id" in sql
