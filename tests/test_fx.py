"""USD/INR lookup: override, daily cache, fallback source, stale limit. No network."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from parakh_advisor.clock import today_ist
from parakh_advisor.sources.fx import get_usd_inr
from parakh_advisor.sources.http import SourceError

ECB = b'{"amount":1.0,"base":"USD","date":"2026-11-23","rates":{"INR":92.92}}'
XE = b"<html>... 1 USD = 92.9484 INR ... 1 INR = 0.01 USD</html>"
ER = b'{"result":"success","rates":{"INR":93.5}}'


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    monkeypatch.delenv("PARAKH_USD_INR", raising=False)


def test_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("PARAKH_USD_INR", "90.5")
    r = get_usd_inr(tmp_path, fetch=lambda u: pytest.fail("no fetch"))
    assert (r.rate, r.as_of) == (90.5, "manual")


def test_xe_first_then_todays_cache(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return XE

    r = get_usd_inr(tmp_path, fetch)
    assert (r.rate, r.source) == (92.9484, "xe.com")
    assert get_usd_inr(tmp_path, lambda u: pytest.fail("cached")).rate == 92.9484
    assert len(calls) == 1


def test_falls_back_when_xe_fails_or_page_changes(tmp_path):
    def fetch(url):
        if "xe.com" in url:
            return b"<html>layout changed</html>"
        if "frankfurter" in url:
            raise SourceError("down")
        return ER

    r = get_usd_inr(tmp_path, fetch)
    assert (r.rate, r.source) == (93.5, "open.er-api.com")


def test_ecb_is_second(tmp_path):
    def fetch(url):
        if "xe.com" in url:
            raise SourceError("blocked")
        return ECB

    assert get_usd_inr(tmp_path, fetch).source == "ECB via Frankfurter"


def _stale(tmp_path, days):
    (tmp_path / "fx_usd_inr.json").write_text(
        json.dumps(
            {"rate": 91.0, "source": "x", "as_of": (today_ist() - timedelta(days=days)).isoformat()}
        )
    )


def test_recent_cache_used_when_sources_fail(tmp_path):
    _stale(tmp_path, 3)
    assert get_usd_inr(tmp_path, lambda u: (_ for _ in ()).throw(SourceError("x"))).rate == 91.0


def test_old_cache_refused(tmp_path):
    _stale(tmp_path, 30)
    with pytest.raises(SourceError, match="PARAKH_USD_INR"):
        get_usd_inr(tmp_path, lambda u: (_ for _ in ()).throw(SourceError("x")))
