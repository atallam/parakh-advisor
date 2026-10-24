"""Fund health card from NAV history (AMFI via mfapi.in). Advisory only.

For each equity fund: returns over 1/3/5 years against a benchmark proxy (an index fund, Direct plan),
how often the fund beat it over rolling one-year windows, volatility and worst fall over 3 years,
and for Regular plans the measured gap to the same scheme's Direct plan. The verdict is a rule, not a
model: HEALTHY, WATCH (slightly behind), LAGGING (more than 3 points a year behind over 3 years),
TOO_NEW (under 3 years of history) or NO_DATA.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from parakh_advisor.sources.http import Fetcher, SourceError, get_json, http_get

NAV_URL = "https://api.mfapi.in/mf/{code}"
SEARCH_URL = "https://api.mfapi.in/mf/search?q={q}"

# Benchmark proxies: Direct-plan index funds (their NAV tracks the index after a small cost).
BENCHMARKS = {
    "smallcap": ("148519", "Nifty Smallcap 250 index fund (Nippon, Direct)"),
    "broad": ("147625", "Nifty 500 index fund (Motilal Oswal, Direct)"),
}
LAG_POINTS = 3.0  # percentage points a year behind over 3 years => LAGGING
DIRECT_GAP_NOTE = 0.3  # points a year; below this, the Regular/Direct gap is not worth a note

Series = list[tuple[date, float]]


class FundHealth(BaseModel):
    scheme_code: str
    status: str  # HEALTHY | WATCH | LAGGING | TOO_NEW | NO_DATA
    benchmark: str = ""
    r1: float | None = None
    r3: float | None = None
    r5: float | None = None
    b1: float | None = None
    b3: float | None = None
    b5: float | None = None
    excess3: float | None = None
    hit_rate: float | None = None
    vol: float | None = None
    max_dd: float | None = None
    direct_gap: float | None = None
    age_years: float | None = None
    lines: list[str] = []


# ---------- NAV data ----------


def _parse(payload: dict) -> Series:
    out: Series = []
    for row in payload.get("data", []):
        try:
            out.append((datetime.strptime(row["date"], "%d-%m-%Y").date(), float(row["nav"])))
        except (KeyError, ValueError):
            continue
    out.sort()
    return [(d, v) for d, v in out if v > 0]


class NavSource:
    def __init__(
        self, cache_dir: str | Path = "data/cache", fetch: Fetcher = http_get, pause: float = 0.3
    ):
        self.cache = Path(cache_dir)
        self.fetch = fetch
        self.pause = pause

    def nav(self, code: str, max_age_days: int = 1) -> Series:
        path = self.cache / f"nav_{code}.json"
        if path.exists() and (time.time() - path.stat().st_mtime) < max_age_days * 86400:
            return [(date.fromisoformat(d), v) for d, v in json.loads(path.read_text("utf-8"))]
        if self.pause:
            time.sleep(self.pause)
        series = _parse(get_json(NAV_URL.format(code=code), self.fetch))
        if not series:
            raise SourceError(f"scheme {code}: mfapi returned no NAV history")
        self.cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([(d.isoformat(), v) for d, v in series]), encoding="utf-8")
        return series

    def direct_twin(self, code: str, name: str) -> str | None:
        """Scheme code of the Direct-Growth plan of the same scheme, found by name; cached."""
        path = self.cache / f"direct_{code}.json"
        if path.exists():
            return json.loads(path.read_text("utf-8")).get("code")
        found = None
        base = _base_tokens(name)
        q = "%20".join(sorted(base, key=name.lower().find)[:4] + ["direct"])
        try:
            for row in get_json(SEARCH_URL.format(q=q), self.fetch):
                n = str(row.get("schemeName", ""))
                nl = n.lower()
                if (
                    "direct" in nl
                    and "growth" in nl
                    and "idcw" not in nl
                    and _base_tokens(n) == base
                ):
                    found = str(row["schemeCode"])
                    break
        except SourceError:
            return None
        self.cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"code": found}), encoding="utf-8")
        return found


def _base_tokens(name: str) -> frozenset[str]:
    drop = {"regular", "direct", "plan", "growth", "option", "-", "idcw", "payout", "reinvestment"}
    return frozenset(
        t for t in name.lower().replace("(", " ").replace(")", " ").split() if t not in drop
    )


# ---------- maths ----------


def _at(series: Series, target: date, tol_days: int = 10) -> float | None:
    """NAV on or just before `target` (within tol_days), else None."""
    best = None
    for d, v in series:
        if d <= target:
            best = (d, v)
        else:
            break
    if best is None or (target - best[0]).days > tol_days:
        return None
    return best[1]


def cagr(series: Series, years: float, end: date) -> float | None:
    v1 = _at(series, end)
    v0 = _at(series, end - timedelta(days=round(years * 365.25)))
    if not v0 or not v1:
        return None
    return ((v1 / v0) ** (1 / years) - 1) * 100


def hit_rate(fund: Series, bench: Series, end: date, months: int = 36) -> float | None:
    wins = total = 0
    for k in range(months):
        t = end - timedelta(days=round(k * 30.44))
        f = cagr(fund, 1, t)
        b = cagr(bench, 1, t)
        if f is None or b is None:
            return None  # not enough history on either side for the full window
        total += 1
        wins += f > b
    return wins / total if total else None


def vol_and_drawdown(
    series: Series, end: date, years: int = 3
) -> tuple[float | None, float | None]:
    start = end - timedelta(days=round(years * 365.25))
    win = [(d, v) for d, v in series if start <= d <= end]
    if len(win) < 100:
        return None, None
    rets = [math.log(b[1] / a[1]) for a, b in zip(win, win[1:], strict=False)]
    vol = statistics.pstdev(rets) * math.sqrt(250) * 100
    peak, dd = win[0][1], 0.0
    for _, v in win:
        peak = max(peak, v)
        dd = min(dd, v / peak - 1)
    return vol, dd * 100


def benchmark_key(category: str) -> str:
    return "smallcap" if "small cap" in category.lower() else "broad"


def assess(
    code: str,
    name: str,
    category: str,
    plan: str | None,
    nav: NavSource,
) -> FundHealth:
    try:
        fund = nav.nav(code)
    except SourceError as exc:
        return FundHealth(
            scheme_code=code, status="NO_DATA", lines=[f"NAV history unavailable ({exc})."]
        )
    end = fund[-1][0]
    age = (end - fund[0][0]).days / 365.25
    bkey = benchmark_key(category)
    bcode, bname = BENCHMARKS[bkey]
    try:
        bench = nav.nav(bcode)
    except SourceError:
        bench = []
    h = FundHealth(scheme_code=code, status="NO_DATA", benchmark=bname, age_years=round(age, 1))
    h.r1, h.r3, h.r5 = (cagr(fund, y, end) for y in (1, 3, 5))
    if bench:
        h.b1, h.b3, h.b5 = (cagr(bench, y, bench[-1][0]) for y in (1, 3, 5))
        h.hit_rate = hit_rate(fund, bench, min(end, bench[-1][0]))
    if h.r3 is not None and h.b3 is not None:
        h.excess3 = h.r3 - h.b3
    h.vol, h.max_dd = vol_and_drawdown(fund, end)

    if plan == "Regular":
        twin = nav.direct_twin(code, name)
        if twin:
            try:
                d3 = cagr(nav.nav(twin), 3, end)
            except SourceError:
                d3 = None
            if d3 is not None and h.r3 is not None:
                h.direct_gap = d3 - h.r3

    lines: list[str] = []
    if age < 3:
        h.status = "TOO_NEW"
        lines.append(f"Only {age:.1f} years of history: too early to judge against a benchmark.")
    elif h.excess3 is None:
        h.status = "NO_DATA"
        lines.append("Benchmark history unavailable, so no comparison was made.")
    else:
        if h.excess3 >= 0 and (h.hit_rate is None or h.hit_rate >= 0.5):
            h.status = "HEALTHY"
        elif h.excess3 > -LAG_POINTS:
            h.status = "WATCH"
        else:
            h.status = "LAGGING"
        lines.append(
            f"3-year return {h.r3:.1f}% a year vs {h.b3:.1f}% for the {bname}: "
            f"{abs(h.excess3):.1f} points a year {'ahead' if h.excess3 >= 0 else 'behind'}."
        )
        if h.r5 is not None and h.b5 is not None:
            lines.append(f"5-year: {h.r5:.1f}% vs {h.b5:.1f}% a year.")
        if h.hit_rate is not None:
            lines.append(
                f"Beat the benchmark in {h.hit_rate * 100:.0f}% of rolling one-year windows over the last 3 years."
            )
    if h.vol is not None and h.max_dd is not None:
        span = "over 3 years" if age >= 3 else f"since launch ({age:.1f} years)"
        lines.append(f"Volatility {h.vol:.0f}% a year; worst fall {span} {h.max_dd:.0f}%.")
    if h.direct_gap is not None and h.direct_gap >= DIRECT_GAP_NOTE:
        lines.append(
            f"Regular plan: its own Direct plan returned {h.direct_gap:.1f} points a year more over 3 years. "
            "Switching has tax and exit-load consequences; check them first."
        )
    h.lines = lines
    return h


# ---------- portfolio level ----------


@dataclass
class Overlap:
    category: str
    names: list[str]
    value_inr: float
    pct: float


def category_overlap(funds: list[tuple[str, str, float]], listed_equity: float) -> list[Overlap]:
    """funds: (name, short category, value). Categories held through 2+ funds."""
    groups: dict[str, list[tuple[str, float]]] = {}
    for name, cat, val in funds:
        groups.setdefault(cat, []).append((name, val))
    out = []
    for cat, rows in groups.items():
        if len(rows) >= 2 and listed_equity:
            tot = sum(v for _, v in rows)
            out.append(Overlap(cat, [n for n, _ in rows], tot, tot / listed_equity * 100))
    return sorted(out, key=lambda o: -o.value_inr)
