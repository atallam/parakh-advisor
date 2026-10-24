from datetime import date

from test_screener_metrics import _workbook

from parakh_advisor.agents import thesis_analyst
from parakh_advisor.llm.client import FakeLLM
from parakh_advisor.metrics.quality import compute
from parakh_advisor.research.documents import load_documents, split_passages
from parakh_advisor.sources.india.screener_export import read_screener
from parakh_advisor.thesis.models import Confidence, DriverStatus

TEXT = "Management said order inflow slowed sharply in the quarter and guided to a weaker second half.\n\nCapex plans were unchanged."


def _docs(tmp_path):
    f = tmp_path / "TEST"
    f.mkdir()
    (f / "2026-07-30_q1_call.txt").write_text(TEXT, encoding="utf-8")
    return load_documents(tmp_path, "TEST")


def _resp():
    return {
        "decision": "NEW",
        "business_summary": "s",
        "why_own": "w",
        "drivers": [
            {
                "id": "D1",
                "statement": "a",
                "kind": "metric",
                "indicator": "roe",
                "direction": "gte",
                "warn_threshold": 5,
                "break_threshold": 2,
            },
            {
                "id": "D2",
                "statement": "b",
                "kind": "metric",
                "indicator": "debt_equity",
                "direction": "lte",
                "warn_threshold": 1,
                "break_threshold": 2,
            },
            {"id": "D3", "statement": "orders keep growing", "kind": "qualitative"},
        ],
        "kill_criteria": [
            {"id": "K1", "description": "k", "indicator": "roe", "op": "<", "threshold": 1}
        ],
        "risks": [{"statement": "r", "evidence_ids": []}],
    }


def test_documents_become_dated_citable_passages(tmp_path):
    docs = _docs(tmp_path)
    assert (
        docs
        and docs[0].id.startswith("DOC.TEST.")
        and docs[0].as_of == date(2026, 7, 30)
        and docs[0].kind == "filing"
    )
    assert split_passages("a\n\nb") == ["a b"]


def test_verbatim_quote_sets_watch_and_lifts_confidence(tmp_path):
    docs = _docs(tmp_path)
    m = compute(read_screener(_workbook(tmp_path / "a.xlsx")))
    r = _resp()
    r["driver_flags"] = [
        {
            "driver_id": "D3",
            "status": "WATCH",
            "evidence_ids": [docs[0].id],
            "quote": "order inflow slowed sharply in the quarter",
        }
    ]
    t = thesis_analyst.run(FakeLLM(r), "X", "TESTCO", None, m, None, docs)
    d3 = next(d for d in t.drivers if d.id == "D3")
    assert d3.status == DriverStatus.WATCH and docs[0].id in d3.evidence_ids
    assert t.confidence != Confidence.LOW or t.stance.value == "INSUFFICIENT"


def test_paraphrased_quote_and_broken_are_refused(tmp_path):
    docs = _docs(tmp_path)
    m = compute(read_screener(_workbook(tmp_path / "a.xlsx")))
    r = _resp()
    r["driver_flags"] = [
        {
            "driver_id": "D3",
            "status": "WATCH",
            "evidence_ids": [docs[0].id],
            "quote": "orders are clearly weakening a lot",
        },
        {
            "driver_id": "D3",
            "status": "BROKEN",
            "evidence_ids": [docs[0].id],
            "quote": "order inflow slowed sharply in the quarter",
        },
    ]
    t = thesis_analyst.run(FakeLLM(r), "X", "TESTCO", None, m, None, docs)
    assert next(d for d in t.drivers if d.id == "D3").status == DriverStatus.UNKNOWN
    assert len(t.rejected_changes) == 2
