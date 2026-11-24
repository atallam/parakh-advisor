"""One clock for the package: UTC instants and the IST date.

    from parakh_advisor.clock import now_utc, today_ist

`date.today()` is the machine's local date. GitHub runners are UTC and filings, results and
prices are dated in IST, so between 18:30 and 24:00 UTC the two disagree. Use `today_ist()` for
any as-of or age decision and `now_utc()` for timestamps. Tests freeze time by patching
`parakh_advisor.clock.now_utc`. Same contract as `parakh.clock` in the sibling repo; kept as a copy
so the two repos stay independent.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_utc() -> dt.datetime:
    """The current instant, timezone-aware UTC."""
    return dt.datetime.now(dt.UTC)


def today_ist() -> dt.date:
    """The current IST calendar date."""
    return now_utc().astimezone(IST).date()
