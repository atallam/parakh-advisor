"""The shared clock gives the IST date, not the machine's."""

import datetime as dt

import pytest

from parakh_advisor import clock


def test_today_ist_is_the_next_day_after_1830_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "now_utc", lambda: dt.datetime(2026, 10, 25, 19, 0, tzinfo=dt.UTC))
    assert clock.today_ist() == dt.date(2026, 10, 26)


def test_today_ist_matches_the_utc_date_in_the_morning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "now_utc", lambda: dt.datetime(2026, 10, 25, 3, 0, tzinfo=dt.UTC))
    assert clock.today_ist() == dt.date(2026, 10, 25)


def test_now_utc_is_timezone_aware() -> None:
    assert clock.now_utc().utcoffset() == dt.timedelta(0)
