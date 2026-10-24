"""US fundamentals from SEC EDGAR "company facts" (XBRL), shaped like a Screener company so the same
metrics, thesis, Skeptic and advice code run on US stocks unchanged.

Units are USD millions. Choices worth knowing (they decide what the ratios mean):
- Operating margin = (operating income + depreciation) / revenue, i.e. an EBITDA-style margin, the same
  basis as the Screener formula. Implemented by setting "Other Income" = PBT + interest - operating income.
- Debt = long-term debt (current + non-current). Operating-lease liabilities are NOT included.
- Quarters are the three-month figures from 10-Q filings, with Q4 derived as fiscal year minus Q1..Q3.
- Market cap = your WealthLens price x shares outstanding on the cover of the latest filing.
- P/E history: fiscal-year-end close (Yahoo, split effects undone) / EPS from as-first-reported diluted shares.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

from parakh_advisor.sources.http import Fetcher, SourceError, get_json, http_get
from parakh_advisor.sources.india.screener_export import ScreenerCompany, Table
from parakh_advisor.sources.us.prices import YahooPrices

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

TAGS = {
    "Sales": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "Net profit": ["NetIncomeLoss", "ProfitLoss"],
    "Profit before tax": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "Operating income": ["OperatingIncomeLoss"],
    "Interest": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "Depreciation": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
        "Depreciation",
    ],
    "CFO": ["NetCashProvidedByUsedInOperatingActivities"],
}
EQUITY = [
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
]
DEBT_NONCURRENT = ["LongTermDebtNoncurrent", "LongTermDebt", "ConvertibleNotesPayableNoncurrent"]
DEBT_CURRENT = ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings"]


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _facts(us: dict, tag: str) -> list[dict]:
    node = us.get(tag)
    return (node or {}).get("units", {}).get("USD", []) if node else []


def _duration_series(
    us: dict, tags: list[str], lo: int, hi: int, fps: tuple[str, ...] | None = None
) -> dict[date, float]:
    """end date -> value for facts whose period length is between lo and hi days. First tag with data
    wins per end date; within a tag the most recently filed value wins (restatements)."""
    out: dict[date, float] = {}
    for tag in tags:
        best: dict[date, tuple[str, float]] = {}
        for f in _facts(us, tag):
            if "start" not in f or "end" not in f:
                continue
            days = (_d(f["end"]) - _d(f["start"])).days
            if not lo <= days <= hi:
                continue
            if fps is not None and f.get("fp") not in fps:
                continue  # 10-Qs also report trailing-twelve-month windows; keep real fiscal years only
            e = _d(f["end"])
            if e not in best or f.get("filed", "") >= best[e][0]:
                best[e] = (f.get("filed", ""), float(f["val"]))
        for e, (_, v) in best.items():
            out.setdefault(e, v)
    return out


def _instant_series(us: dict, tags: list[str]) -> dict[date, float]:
    out: dict[date, float] = {}
    for tag in tags:
        best: dict[date, tuple[str, float]] = {}
        for f in _facts(us, tag):
            if "end" not in f or "start" in f:
                continue
            e = _d(f["end"])
            if e not in best or f.get("filed", "") >= best[e][0]:
                best[e] = (f.get("filed", ""), float(f["val"]))
        for e, (_, v) in best.items():
            out.setdefault(e, v)
    return out


def diluted_shares_first_reported(us: dict) -> dict[date, float]:
    """Fiscal year end -> weighted diluted shares as first reported (before any later split
    restatement), the count that goes with the price quoted at the time."""
    node = us.get("WeightedAverageNumberOfDilutedSharesOutstanding", {})
    best: dict[date, tuple[str, float]] = {}
    for f in node.get("units", {}).get("shares", []):
        if "start" not in f or "end" not in f or f.get("fp") != "FY":
            continue
        if not 340 <= (_d(f["end"]) - _d(f["start"])).days <= 380:
            continue
        e = _d(f["end"])
        if e not in best or f.get("filed", "9999") < best[e][0]:
            best[e] = (f.get("filed", "9999"), float(f["val"]))
    return {e: v for e, (_, v) in best.items()}


def _near(series: dict[date, float], end: date, tol: int = 10) -> float | None:
    if end in series:
        return series[end]
    for e, v in series.items():
        if abs((e - end).days) <= tol:
            return v
    return None


def _quarters(annual: dict[date, float], q3m: dict[date, float]) -> dict[date, float]:
    """Three-month figures plus a derived Q4 for each fiscal year that has Q1..Q3 reported."""
    out = dict(q3m)
    for fy_end, fy_val in annual.items():
        inside = sorted(e for e in q3m if 0 < (fy_end - e).days < 300)
        if len(inside) >= 3 and fy_end not in out:
            last3 = inside[-3:]
            if (fy_end - last3[-1]).days > 60:  # the Q3 end is ~90 days before year end
                out[fy_end] = fy_val - sum(q3m[e] for e in last3)
    return out


def shares_outstanding(facts: dict) -> float | None:
    """Cover-page share count when present (summed across classes); else the latest reported
    common shares outstanding; else the latest diluted weighted-average (slightly high). Multi-class
    companies such as Alphabet and Meta usually need the fallbacks."""
    node = facts.get("facts", {})
    dei = (
        node.get("dei", {})
        .get("EntityCommonStockSharesOutstanding", {})
        .get("units", {})
        .get("shares", [])
    )
    if dei:
        latest: dict[str, float] = {}
        for f in dei:
            latest[f["end"]] = latest.get(f["end"], 0.0) + float(f["val"])
        return latest[max(latest)]
    us = node.get("us-gaap", {})
    for tag in ("CommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding"):
        rows = us.get(tag, {}).get("units", {}).get("shares", [])
        if rows:
            last = max(f["end"] for f in rows)
            return max(float(f["val"]) for f in rows if f["end"] == last)
    return None


def to_company(
    name: str,
    facts: dict,
    price_usd: float | None,
    month_prices: dict[tuple[int, int], float] | None = None,
) -> ScreenerCompany:
    us = facts.get("facts", {}).get("us-gaap", {})
    annual = {k: _duration_series(us, t, 340, 380, ("FY",)) for k, t in TAGS.items()}
    quarterly = {
        k: _duration_series(us, TAGS[k], 80, 100, ("Q1", "Q2", "Q3"))
        for k in ("Sales", "Net profit")
    }
    equity, d_nc, d_c = (
        _instant_series(us, EQUITY),
        _instant_series(us, DEBT_NONCURRENT),
        _instant_series(us, DEBT_CURRENT),
    )

    ends = sorted(annual["Sales"])[-10:]
    if len(ends) < 3:
        raise SourceError(
            f"{name}: EDGAR has fewer than 3 annual revenue figures; cannot build fundamentals"
        )
    M = 1e6
    rows: dict[str, list[float | None]] = {
        k: []
        for k in (
            "Sales",
            "Other Income",
            "Depreciation",
            "Interest",
            "Profit before tax",
            "Net profit",
        )
    }
    bal: dict[str, list[float | None]] = {
        "Equity Share Capital": [],
        "Reserves": [],
        "Borrowings": [],
    }
    cfo: list[float | None] = []
    for e in ends:
        g = lambda k, e=e: v / M if (v := _near(annual[k], e)) is not None else None  # noqa: E731
        sales, pbt, intr, opinc = (
            g("Sales"),
            g("Profit before tax"),
            g("Interest"),
            g("Operating income"),
        )
        rows["Sales"].append(sales)
        rows["Net profit"].append(g("Net profit"))
        rows["Profit before tax"].append(pbt)
        rows["Interest"].append(intr if intr is not None else 0.0)
        rows["Depreciation"].append(g("Depreciation"))
        rows["Other Income"].append(None if None in (pbt, opinc) else pbt + (intr or 0.0) - opinc)
        eq = _near(equity, e)
        bal["Equity Share Capital"].append(0.0)
        bal["Reserves"].append(None if eq is None else eq / M)
        nc, cu = _near(d_nc, e), _near(d_c, e)
        bal["Borrowings"].append(
            None if nc is None and cu is None else ((nc or 0.0) + (cu or 0.0)) / M
        )
        cfo.append(g("CFO"))

    qnp = _quarters(annual["Net profit"], quarterly["Net profit"])
    qsales = _quarters(annual["Sales"], quarterly["Sales"])
    qends = sorted(qnp)[-12:]
    shares = shares_outstanding(facts)
    mcap = price_usd * shares / M if (price_usd and shares) else None
    px_row: list[float | None] = []
    sh_row: list[float | None] = []
    if month_prices:
        dil = diluted_shares_first_reported(us)
        for e in ends:
            sh = _near(dil, e)
            px_row.append(month_prices.get((e.year, e.month)) if sh else None)
            sh_row.append(sh / M if sh else None)
    return ScreenerCompany(
        name=name,
        version="edgar",
        price=price_usd,
        market_cap=mcap,
        face_value=None,
        annual=Table(dates=ends, cols=list(range(len(ends))), rows=rows),
        quarters=Table(
            dates=qends,
            cols=list(range(len(qends))),
            rows={
                "Net profit": [qnp[e] / M for e in qends],
                "Sales": [qsales.get(e, float("nan")) / M for e in qends],
            },
        ),
        balance=Table(dates=ends, cols=list(range(len(ends))), rows=bal),
        cashflow=Table(
            dates=ends, cols=list(range(len(ends))), rows={"Cash from Operating Activity": cfo}
        ),
        year_end_price=Table(dates=ends, cols=list(range(len(ends))), rows={"Price": px_row})
        if px_row
        else Table(),
        derived=Table(
            dates=ends,
            cols=list(range(len(ends))),
            rows={"Adjusted Equity Shares in Cr": sh_row},  # millions of shares here
        )
        if sh_row
        else Table(),
        source_file="SEC EDGAR companyfacts",
        money_unit="USD m",
    )


class Edgar:
    def __init__(self, cache_dir: str | Path = "data/cache", fetch: Fetcher = http_get):
        self.cache = Path(cache_dir)
        self.fetch = fetch

    def cik(self, ticker: str) -> int:
        path = self.cache / "sec_tickers.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = get_json(TICKERS_URL, self.fetch)
            self.cache.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        for row in data.values():
            if row["ticker"].upper() == ticker.upper():
                return int(row["cik_str"])
        raise SourceError(f"EDGAR has no CIK for ticker {ticker}")

    def facts(self, ticker: str, max_age_days: int = 7) -> dict:
        cik = self.cik(ticker)
        path = self.cache / f"edgar_{cik}.json"
        if (
            path.exists()
            and (datetime.now().timestamp() - path.stat().st_mtime) < max_age_days * 86400
        ):
            return json.loads(path.read_text(encoding="utf-8"))
        data = get_json(FACTS_URL.format(cik=cik), self.fetch)
        self.cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def company(self, ticker: str, name: str, price_usd: float | None) -> ScreenerCompany:
        month_prices = None
        try:
            month_prices = YahooPrices(self.cache, self.fetch).month_end_prices(ticker)
        except SourceError as exc:
            print(f"  - {ticker}: no price history, valuation will be NA ({exc})", file=sys.stderr)
        return to_company(name, self.facts(ticker), price_usd, month_prices)
