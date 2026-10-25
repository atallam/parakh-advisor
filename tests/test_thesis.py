from datetime import date

import pytest
from test_screener_metrics import _workbook

from parakh_advisor.agents import thesis_analyst
from parakh_advisor.llm.client import FakeLLM, LLMError, parse_json_object
from parakh_advisor.metrics.quality import compute
from parakh_advisor.sources.india.screener_export import read_screener
from parakh_advisor.thesis.models import ChangeDecision, Stance
from parakh_advisor.thesis.rules import derive_stance
from parakh_advisor.thesis.store import ThesisStore

NEW = {
    "decision": "NEW",
    "business_summary": "A test company.",
    "why_own": "Compounds profit with low debt.",
    "drivers": [
        {
            "id": "D1",
            "statement": "ROE stays high",
            "kind": "metric",
            "indicator": "roe",
            "direction": "gte",
            "warn_threshold": 15,
            "break_threshold": 10,
            "evidence_ids": ["MET.roe@202603", "MET.bogus@1"],
        },
        {
            "id": "D2",
            "statement": "Debt stays low",
            "kind": "metric",
            "indicator": "debt_equity",
            "direction": "lte",
            "warn_threshold": 0.5,
            "break_threshold": 1.0,
        },
        {"id": "D3", "statement": "Management keeps allocating well", "kind": "qualitative"},
    ],
    "kill_criteria": [
        {
            "id": "K1",
            "description": "Debt/equity above 2",
            "indicator": "debt_equity",
            "op": ">",
            "threshold": 2,
        }
    ],
    "risks": [{"statement": "Leverage could rise", "evidence_ids": ["MET.debt_equity@202603"]}],
}


@pytest.fixture
def metrics(tmp_path):
    return compute(read_screener(_workbook(tmp_path / "a.xlsx")))


def test_new_thesis_scores_drivers_in_code_and_drops_unknown_evidence(metrics):
    t = thesis_analyst.run(FakeLLM(NEW), "X", "TESTCO", None, metrics, None)
    assert t.version == 1 and t.change_decision == ChangeDecision.NEW
    d = {x.id: x for x in t.drivers}
    assert d["D1"].status == "WATCH"  # ROE 14.5 is below the warn line of 15, above break 10
    assert d["D2"].status == "OK"  # debt/equity 0.2 is under 0.5
    assert d["D3"].status == "UNKNOWN"  # qualitative drivers are never scored by code
    assert d["D1"].evidence_ids == ["MET.roe@202603"]  # the invented id was dropped
    assert not any(k.tripped for k in t.kill_criteria)


def test_stance_insufficient_with_short_history(metrics):
    t = thesis_analyst.run(FakeLLM(NEW), "X", "TESTCO", None, metrics, None)
    assert metrics.quarters_reported == 4 and t.stance == Stance.INSUFFICIENT


def test_amend_without_newer_evidence_is_rejected(metrics):
    store_prior = thesis_analyst.run(FakeLLM(NEW), "X", "TESTCO", None, metrics, None)
    amend = {
        **NEW,
        "decision": "AMEND",
        "why_own": "Now a turnaround story",
        "changes": [
            {
                "field": "why_own",
                "from_value": "a",
                "to_value": "b",
                "new_evidence_ids": ["MET.roe@202603"],
            }
        ],
    }
    t2 = thesis_analyst.run(FakeLLM(amend), "X", "TESTCO", None, metrics, store_prior)
    assert t2.version == 2 and t2.change_decision == ChangeDecision.REAFFIRM
    assert t2.why_own == store_prior.why_own and t2.rejected_changes


def test_reaffirm_keeps_preregistered_thresholds(metrics):
    prior = thesis_analyst.run(FakeLLM(NEW), "X", "TESTCO", None, metrics, None)
    moved = {
        **NEW,
        "decision": "REAFFIRM",
        "drivers": [{**NEW["drivers"][0], "warn_threshold": 1}, *NEW["drivers"][1:]],
    }
    t2 = thesis_analyst.run(FakeLLM(moved), "X", "TESTCO", None, metrics, prior)
    assert t2.drivers[0].warn_threshold == 15


def test_kill_criterion_trips_in_code(metrics):
    bad = {
        **NEW,
        "kill_criteria": [
            {
                "id": "K1",
                "description": "ROE below 50",
                "indicator": "roe",
                "op": "<",
                "threshold": 50,
            }
        ],
    }
    t = thesis_analyst.run(FakeLLM(bad), "X", "TESTCO", None, metrics, None)
    assert t.kill_criteria[0].tripped and t.stance == Stance.BROKEN


def test_invalid_output_raises(metrics):
    with pytest.raises(LLMError):
        thesis_analyst.run(FakeLLM({"decision": "NEW"}), "X", "TESTCO", None, metrics, None)


def test_replay_same_inputs_same_digest_and_stance(metrics):
    a = thesis_analyst.run(FakeLLM(NEW), "X", "TESTCO", None, metrics, None)
    b = thesis_analyst.run(FakeLLM(NEW), "X", "TESTCO", None, metrics, None)
    assert a.inputs_digest == b.inputs_digest and a.stance == b.stance


def test_store_is_append_only(tmp_path, metrics):
    s = ThesisStore(tmp_path)
    t = thesis_analyst.run(FakeLLM(NEW), "US:NVDA", "TESTCO", None, metrics, None)
    s.save(t)
    assert s.latest("US:NVDA").version == 1
    with pytest.raises(FileExistsError):
        s.save(t)


def test_parse_json_object_handles_fences():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(LLMError):
        parse_json_object("sorry, here you go")


def test_stance_table_needs_eight_quarters():
    assert derive_stance([], [], 12)[0] == Stance.INSUFFICIENT
    assert date(2026, 1, 1)


def test_anthropic_client_retries_without_temperature(monkeypatch):
    from parakh_advisor.llm.client import AnthropicLLM

    class Block:
        type = "text"
        text = '{"ok": 1}'

    class Msg:
        content = [Block()]

    class Messages:
        def create(self, **kw):
            if "temperature" in kw:
                raise TypeError("create() got an unexpected keyword argument 'temperature'")
            return Msg()

    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "m"
    llm._client = type("C", (), {"messages": Messages()})()
    assert llm.complete_json("s", "u") == {"ok": 1}


def test_one_driver_on_watch_means_weakening_not_intact():
    from parakh_advisor.thesis.models import Driver, DriverStatus

    ds = [
        Driver(id=f"D{i}", statement="x", kind="metric", status=s)
        for i, s in enumerate(
            [DriverStatus.OK, DriverStatus.OK, DriverStatus.OK, DriverStatus.WATCH]
        )
    ]
    assert derive_stance(ds, [], 12, sourced=True)[0] == Stance.WEAKENING


def test_numbers_only_thesis_is_low_confidence():
    from parakh_advisor.thesis.models import Confidence, Driver, DriverStatus

    ds = [
        Driver(id=f"D{i}", statement="x", kind="metric", status=DriverStatus.OK) for i in range(3)
    ]
    assert derive_stance(ds, [], 12, sourced=False) == (Stance.INTACT, Confidence.LOW)
    assert derive_stance(ds, [], 12, sourced=True) == (Stance.INTACT, Confidence.MEDIUM)


def test_loss_is_stated_as_evidence(metrics):
    assert metrics.get("np_fy").value == 40.0 and metrics.get("loss_quarters_4").value == 0


def test_never_profitable_company_is_insufficient_not_intact(metrics):
    from parakh_advisor.thesis.models import Driver, DriverStatus

    ds = [
        Driver(id=f"D{i}", statement="x", kind="metric", status=DriverStatus.OK) for i in range(3)
    ]
    assert (
        derive_stance(ds, [], 12, sourced=True, no_earnings_record=True)[0] == Stance.INSUFFICIENT
    )
    assert metrics.profitable_years == 5 and metrics.ttm_profit == 40.0


def test_code_adds_cash_conversion_driver_when_profit_is_not_backed_by_cash(metrics):
    # make the red flag real: profit positive, operating cash flow negative
    from parakh_advisor.thesis.evidence import from_metrics
    from parakh_advisor.thesis.rules import hygiene_drivers

    ev = [
        e.model_copy(update={"value": -0.5}) if e.id.startswith("MET.cfo_np") else e
        for e in from_metrics(metrics)
    ]
    added = hygiene_drivers([], ev)
    assert [d.indicator for d in added] == ["cfo_np"] and added[0].break_threshold is None


def test_hygiene_skips_indicators_the_model_already_covers(metrics):
    from parakh_advisor.thesis.evidence import from_metrics
    from parakh_advisor.thesis.models import Driver
    from parakh_advisor.thesis.rules import hygiene_drivers

    ev = [
        e.model_copy(update={"value": -0.5}) if e.id.startswith("MET.cfo_np") else e
        for e in from_metrics(metrics)
    ]
    mine = [Driver(id="D1", statement="x", kind="metric", indicator="cfo_np", direction="gte")]
    assert hygiene_drivers(mine, ev) == []


def test_store_uses_symbol_folder_and_migrates_legacy(tmp_path):
    from parakh_advisor.thesis.store import ThesisStore

    (tmp_path / "INE0HOQ01053").mkdir()
    (tmp_path / "INE0HOQ01053" / "v0001.json").write_text("{}")
    s = ThesisStore(tmp_path, {"INE0HOQ01053": "GROWW", "US:AMD": "AMD"})
    assert s._dir("INE0HOQ01053") == tmp_path / "GROWW"
    assert (tmp_path / "GROWW" / "v0001.json").exists()
    assert not (tmp_path / "INE0HOQ01053").exists()
    assert s._dir("US:AMD") == tmp_path / "AMD"
    assert s._dir("UNKNOWN:1") == tmp_path / "UNKNOWN_1"


def test_cut_off_reply_is_reported_not_parsed(monkeypatch):
    import pytest

    from parakh_advisor.llm.client import AnthropicLLM, LLMError

    class Block:
        type = "text"
        text = '{"decision": "AMEND", "business_summary": "cut'

    class Msg:
        content = [Block()]
        stop_reason = "max_tokens"

    class Client:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                return Msg()

    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model, llm._client = "x", Client()
    with pytest.raises(LLMError, match="cut off"):
        llm.complete_json("s", "u", max_tokens=100)


def test_parse_json_object_ignores_junk_after_the_object():
    text = '{"action":"tool","tool":"get","args":{"id":"x"}}\n\n\n<invoke name="x">\n</invoke>'
    assert parse_json_object(text)["tool"] == "get"
    import pytest

    with pytest.raises(LLMError):
        parse_json_object('Sure! {"a": 1}')
