"""Deterministic quality and valuation metrics from a Screener export.

Numbers come from code, never from the LLM. Every metric is a `Metric` carrying its value, the
formula used and, when it cannot be computed or does not apply, a plain reason. Profiles:
  standard : normal operating company
  bank     : margin, debt/equity, ROCE and interest cover are meaningless (interest is the cost of
             goods), so they return n/a with a reason; ROE, P/B and growth still apply.
Money in Rs crore. Percentages are returned as numbers (12.5 means 12.5 %).
"""

from __future__ import annotations

import math
import statistics
from datetime import date

from pydantic import BaseModel

from parakh_advisor.sources.india.screener_export import ScreenerCompany, Table


class Metric(BaseModel):
    key: str
    label: str
    value: float | None
    unit: str  # "%", "x", "yrs", "Rs cr"
    basis: str  # formula / period, e.g. "FY26 PBT+interest+depreciation-other income / sales"
    note: str | None = None  # why n/a, or a caveat


class CompanyMetrics(BaseModel):
    name: str
    profile: str
    fy_end: date | None
    quarter_end: date | None
    quarters_reported: int = 0
    profitable_years: int = 0  # fiscal years with positive net profit
    ttm_profit: float | None = None  # trailing 4 quarters, Rs cr
    price: float | None
    market_cap_cr: float | None
    metrics: list[Metric]
    history_pe: list[tuple[int, float]] = []  # (fiscal year, year-end price / EPS)

    def get(self, key: str) -> Metric | None:
        return next((m for m in self.metrics if m.key == key), None)


def _last(xs: list[float | None]) -> float | None:
    return xs[-1] if xs else None


def _at(xs: list[float | None], i: int) -> float | None:
    return xs[i] if -len(xs) <= i < len(xs) else None


def _cagr(xs: list[float | None], years: int) -> float | None:
    end, start = _at(xs, -1), _at(xs, -1 - years)
    if end is None or start is None or start <= 0 or end <= 0:
        return None  # CAGR is undefined across zero or negative values
    return ((end / start) ** (1 / years) - 1) * 100


def _div(a: float | None, b: float | None) -> float | None:
    return None if a is None or b in (None, 0) else a / b


def _m(key, label, value, unit, basis, note=None) -> Metric:
    return Metric(
        key=key,
        label=label,
        value=None if value is None else round(value, 2),
        unit=unit,
        basis=basis,
        note=note,
    )


def _na(key, label, unit, reason) -> Metric:
    return Metric(key=key, label=label, value=None, unit=unit, basis="not applicable", note=reason)


def _equity(bal: Table, i: int = -1) -> float | None:
    cap, res = _at(bal.get("Equity Share Capital"), i), _at(bal.get("Reserves"), i)
    return None if cap is None or res is None else cap + res


def _op_margin(a: Table, i: int) -> float | None:
    pbt, intr, dep, oi, sales = (
        _at(a.get(k), i)
        for k in ("Profit before tax", "Interest", "Depreciation", "Other Income", "Sales")
    )
    if None in (pbt, intr, dep, oi) or not sales:
        return None
    return (pbt + intr + dep - oi) / sales * 100


def _clean(x: float | None) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def _year_ago(dates: list[date], i: int) -> int | None:
    """Index of the quarter about one year before quarter i (350-380 days), or None."""
    for j in range(i - 1, -1, -1):
        gap = (dates[i] - dates[j]).days
        if 350 <= gap <= 380:
            return j
        if gap > 380:
            break
    return None


def quarterly_metrics(q: Table) -> list[Metric]:
    """Latest-quarter signals, each measured against the same quarter a year earlier so seasonality
    cancels. Annual metrics lag by up to a year; these show a quarter that has already turned."""
    dates = q.dates
    sales = [_clean(x) for x in q.get("Sales")]
    prof = [_clean(x) for x in q.get("Net profit")]
    i = len(dates) - 1
    j = _year_ago(dates, i) if i >= 0 else None
    when = f"quarter ended {dates[i]:%b %Y}" if i >= 0 else "latest quarter"
    vs = f"{when} vs {dates[j]:%b %Y}" if j is not None else when

    def pct(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None or b <= 0 else (a / b - 1) * 100

    s_now, s_then = (sales[i], sales[j]) if j is not None else (None, None)
    n_now, n_then = (prof[i], prof[j]) if j is not None else (None, None)
    margin_chg = (
        n_now / s_now * 100 - n_then / s_then * 100
        if None not in (n_now, n_then, s_now, s_then) and s_now > 0 and s_then > 0
        else None
    )
    run: int | None = None
    if j is not None and n_now is not None and n_then is not None:
        run = 0
        k = i
        while k >= 0 and run < 4:
            jk = _year_ago(dates, k)
            if jk is None or prof[k] is None or prof[jk] is None or prof[k] >= prof[jk]:
                break
            run += 1
            k -= 1
    no_pair = None if j is not None else "no quarter a year earlier in the data"
    return [
        _m(
            "q_sales_yoy",
            "Revenue growth, latest quarter YoY",
            pct(s_now, s_then),
            "%",
            f"sales, {vs}",
            no_pair or (None if pct(s_now, s_then) is not None else "year-ago sales not positive"),
        ),
        _m(
            "q_np_yoy",
            "Net profit growth, latest quarter YoY",
            pct(n_now, n_then),
            "%",
            f"net profit, {vs}",
            no_pair or (None if pct(n_now, n_then) is not None else "year-ago profit not positive"),
        ),
        _m(
            "q_npm_chg",
            "Net margin change, latest quarter YoY",
            margin_chg,
            "pp",
            f"net profit / sales, {vs}",
            no_pair or (None if margin_chg is not None else "sales missing"),
        ),
        _m(
            "q_np_down_run",
            "Consecutive quarters of lower profit YoY",
            run,
            "count",
            f"newest quarters whose net profit is below the same quarter a year earlier (max 4), to {when}",
            no_pair,
        ),
    ]


def compute(c: ScreenerCompany, profile: str = "standard") -> CompanyMetrics:
    a, q, b, cf = c.annual, c.quarters, c.balance, c.cashflow
    fy = a.dates[-1] if a.dates else None
    fy_lbl = f"FY{fy.year % 100:02d}" if fy else "latest FY"
    bank = profile == "bank"
    out: list[Metric] = []

    sales, np_ = a.get("Sales"), a.get("Net profit")
    for yrs in (3, 5):
        out.append(
            _m(
                f"rev_cagr_{yrs}",
                f"Revenue growth, {yrs}y CAGR",
                _cagr(sales, yrs),
                "%",
                f"Sales, {yrs} years to {fy_lbl}",
                None
                if _cagr(sales, yrs) is not None
                else "needs positive values for the full period",
            )
        )
    out.append(
        _m(
            "np_cagr_3",
            "Net profit growth, 3y CAGR",
            _cagr(np_, 3),
            "%",
            f"Net profit, 3 years to {fy_lbl}",
            None
            if _cagr(np_, 3) is not None
            else "undefined: profit was zero or negative at the start or end",
        )
    )

    if bank:
        for k, lbl, u in (
            ("op_margin", "Operating margin", "%"),
            ("debt_equity", "Debt / equity", "x"),
            ("roce", "ROCE", "%"),
            ("int_cover", "Interest cover", "x"),
        ):
            out.append(
                _na(
                    k,
                    lbl,
                    u,
                    "banks fund themselves with deposits; this ratio does not describe a bank",
                )
            )
    else:
        om, om3 = _op_margin(a, -1), _op_margin(a, -4)
        out.append(
            _m(
                "op_margin",
                "Operating margin",
                om,
                "%",
                f"{fy_lbl} (PBT + interest + depreciation - other income) / sales",
            )
        )
        out.append(
            _m(
                "op_margin_chg",
                "Operating margin change, 3y",
                None if om is None or om3 is None else om - om3,
                "pp",
                f"{fy_lbl} vs 3 years earlier",
            )
        )
        debt, eq = _last(b.get("Borrowings")), _equity(b)
        out.append(
            _m(
                "debt_equity",
                "Debt / equity",
                _div(debt, eq),
                "x",
                f"{fy_lbl} borrowings / (share capital + reserves)",
                "borrowings include lease liabilities" if profile == "airline_lease" else None,
            )
        )
        pbt, intr = _last(a.get("Profit before tax")), _last(a.get("Interest"))
        capital = None if None in (debt, eq) else debt + eq
        roce = _div(pbt + intr, capital) if None not in (pbt, intr) else None
        out.append(
            _m(
                "roce",
                "ROCE",
                None if roce is None else roce * 100,
                "%",
                f"{fy_lbl} (PBT + interest) / (equity + borrowings), year-end capital",
            )
        )
        out.append(
            _m(
                "int_cover",
                "Interest cover",
                _div(None if None in (pbt, intr) else pbt + intr, intr),
                "x",
                f"{fy_lbl} (PBT + interest) / interest",
                "no interest expense" if intr == 0 else None,
            )
        )

    eq_now, eq_prev = _equity(b), _equity(b, -2)
    avg_eq = None if eq_now is None else (eq_now if eq_prev is None else (eq_now + eq_prev) / 2)
    ok = (_last(np_) or 0) > 0 and (avg_eq or 0) > 0
    roe = _div(_last(np_), avg_eq) if ok else None
    out.append(
        _m(
            "roe",
            "ROE",
            None if roe is None else roe * 100,
            "%",
            f"{fy_lbl} net profit / average equity",
            None if ok else "not meaningful: loss-making or negative equity",
        )
    )

    cfo = _last(cf.get("Cash from Operating Activity"))
    if bank:
        out.append(
            _na(
                "cfo_np",
                "Cash flow / profit",
                "x",
                "operating cash flow for a bank is dominated by loan and deposit movements",
            )
        )
    else:
        out.append(
            _m(
                "cfo_np",
                "Cash flow / profit",
                _div(cfo, _last(np_)) if (_last(np_) or 0) > 0 else None,
                "x",
                f"{fy_lbl} cash from operations / net profit",
                None if (_last(np_) or 0) > 0 else "profit not positive",
            )
        )

    # profit level: so a loss is stated as a loss, not hidden behind an n/a ratio
    qvals = [x for x in q.get("Net profit") if x is not None]
    out.append(
        _m(
            "np_fy",
            "Net profit, latest fiscal year",
            _last(np_),
            c.money_unit,
            f"{fy_lbl} net profit",
        )
    )
    last4 = qvals[-4:]
    out.append(
        _m(
            "np_ttm",
            "Net profit, trailing 4 quarters",
            sum(last4) if len(last4) == 4 else None,
            c.money_unit,
            "sum of the last 4 reported quarters",
        )
    )
    out.append(
        _m(
            "loss_quarters_4",
            "Loss-making quarters in the last 4",
            sum(x < 0 for x in last4) if len(last4) == 4 else None,
            "count",
            "quarters with negative net profit",
        )
    )

    # valuation
    mcap = c.market_cap
    qnp = [x for x in q.get("Net profit") if x is not None]
    ttm = sum(qnp[-4:]) if len(qnp) >= 4 else None
    qd = q.dates[-1] if q.dates else None
    pe = _div(mcap, ttm) if (ttm or 0) > 0 else None
    out.append(
        _m(
            "pe_ttm",
            "P/E (trailing 4 quarters)",
            pe,
            "x",
            f"market cap / sum of last 4 quarterly net profits (to {qd})",
            None if pe is not None else "trailing profit not positive",
        )
    )
    out.append(_m("pb", "Price / book", _div(mcap, eq_now), "x", f"market cap / {fy_lbl} equity"))

    # PE history: year-end price / EPS, EPS from annual profit and split-adjusted shares
    shares = c.derived.get("Adjusted Equity Shares in Cr")
    px = c.year_end_price.rows.get("Price", [])
    hist: list[tuple[int, float]] = []
    for i, d in enumerate(a.dates):
        p, n, s = _at(px, i), _at(np_, i), _at(shares, i)
        if p and n and s and n > 0:
            hist.append((d.year, round(p / (n / s), 1)))
    recent = [v for _, v in hist[-5:]]
    # If trailing profit is far above last fiscal year's (often one-off gains), comparing that P/E with
    # history would flatter the stock. Use the fiscal-year P/E in that case and say so.
    fy_np = _last(np_)
    pe_cmp, pe_note = pe, "trailing P/E"
    if pe is not None and ttm and fy_np and fy_np > 0 and ttm > 1.4 * fy_np and mcap:
        pe_cmp, pe_note = (
            mcap / fy_np,
            f"{fy_lbl} P/E (trailing profit is {ttm / fy_np:.1f}x the fiscal year's)",
        )
    if pe_cmp is not None and len(recent) >= 3:
        med = statistics.median(recent)
        out.append(
            _m(
                "pe_vs_hist",
                "P/E vs own 5y median",
                (pe_cmp / med - 1) * 100,
                "%",
                f"{pe_note} vs median of {len(recent)} year-end P/Es ({med:.1f}x)",
                "history uses year-end prices; a loose guide, not a target",
            )
        )
    else:
        out.append(
            _m(
                "pe_vs_hist",
                "P/E vs own 5y median",
                None,
                "%",
                "not computed",
                "fewer than 3 profitable years of price history, or no current P/E",
            )
        )

    out.extend(quarterly_metrics(q))

    return CompanyMetrics(
        name=c.name,
        profile=profile,
        fy_end=fy,
        quarter_end=qd,
        quarters_reported=len(q.dates),
        profitable_years=sum(1 for x in np_ if x is not None and x > 0),
        ttm_profit=ttm,
        price=c.price,
        market_cap_cr=mcap,
        metrics=out,
        history_pe=hist,
    )
