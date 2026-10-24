"""US share price history from Yahoo's public chart endpoint (monthly bars, with stock splits).

Used only to compare today's P/E with the stock's own past P/E. Yahoo's closes are adjusted for later
splits; SEC share counts are as originally reported. So each past close is scaled back to the price
actually quoted at the time (multiplied by every later split), which matches the as-reported EPS.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime
from pathlib import Path

from parakh_advisor.sources.http import Fetcher, SourceError, get_json, http_get

CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=12y&interval=1mo&events=split"
)


class YahooPrices:
    def __init__(
        self, cache_dir: str | Path = "data/cache", fetch: Fetcher = http_get, pause: float = 2.0
    ):
        self.cache = Path(cache_dir)
        self.fetch = fetch
        self.pause = pause

    def raw(self, ticker: str, max_age_days: int = 1) -> dict:
        path = self.cache / f"yahoo_{ticker.upper()}.json"
        if (
            path.exists()
            and (datetime.now().timestamp() - path.stat().st_mtime) < max_age_days * 86400
        ):
            return json.loads(path.read_text(encoding="utf-8"))
        data = self._download(ticker, path)
        self.cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def _download(self, ticker: str, stale: Path) -> dict:
        """Yahoo rate-limits bursts (HTTP 429): pause before each call, back off and retry, and fall
        back to an older cached copy rather than lose the valuation."""
        last: SourceError | None = None
        for attempt in range(3):
            time.sleep(self.pause * (attempt + 1) if self.pause else 0)
            try:
                return get_json(CHART_URL.format(ticker=ticker.upper()), self.fetch)
            except SourceError as exc:
                last = exc
        if stale.exists():
            return json.loads(stale.read_text(encoding="utf-8"))
        raise last or SourceError(f"{ticker}: price download failed")

    def month_end_prices(self, ticker: str) -> dict[tuple[int, int], float]:
        """(year, month) -> close as quoted at the time (split-adjustment undone)."""
        return month_end_prices(self.raw(ticker), ticker)


def month_end_prices(data: dict, ticker: str = "") -> dict[tuple[int, int], float]:
    try:
        res = data["chart"]["result"][0]
        stamps = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SourceError(f"{ticker}: unexpected price data from Yahoo") from exc
    splits = []
    for s in ((res.get("events") or {}).get("splits") or {}).values():
        splits.append(
            (
                datetime.fromtimestamp(int(s["date"]), tz=UTC).date(),
                float(s["numerator"]) / float(s["denominator"]),
            )
        )
    out: dict[tuple[int, int], float] = {}
    for ts, close in zip(stamps, closes, strict=False):
        if close is None:
            continue
        d = datetime.fromtimestamp(int(ts), tz=UTC).date()
        factor = 1.0
        for sd, ratio in splits:
            if sd > d and (sd.year, sd.month) != (d.year, d.month):
                factor *= ratio
            elif sd > d:
                # a split inside the same month as the bar: the month-end close is already post-split
                continue
        out[(d.year, d.month)] = float(close) * factor
    return out


def price_at(prices: dict[tuple[int, int], float], end: date) -> float | None:
    return prices.get((end.year, end.month))
