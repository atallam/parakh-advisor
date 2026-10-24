"""Stock-level overlap from the funds' own monthly portfolio files (xlsx or csv from the AMC website).

Drop one file per fund in data/inbox/funds/. The reader finds the header row itself (a name column and a
"% to NAV" style column), so exact AMC layouts do not matter. The file is matched to one of your funds
by the words in its file name. Weights may be given as 5.23 or 0.0523; both are handled.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

NAME_HDR = re.compile(
    r"(name of (the )?(instrument|security)|^instrument|^security|^issuer|^company|^name$|stock)",
    re.I,
)
PCT_HDR = re.compile(
    r"(% *(to|of)? *(net|nav|aum|assets)|% *to *nav|weight|holding *%|market value *%|% *(of)? *market value|^% )",
    re.I,
)
ISIN_HDR = re.compile(r"isin", re.I)
GENERIC = {
    "fund",
    "plan",
    "direct",
    "regular",
    "growth",
    "option",
    "scheme",
    "the",
    "of",
    "-",
    "portfolio",
    "india",
}
SUFFIX = {
    "inc",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "plc",
    "co",
    "company",
    "class",
    "a",
    "b",
    "c",
    "common",
    "stock",
    "the",
    "holdings",
    "group",
    "adr",
    "ord",
}


@dataclass
class FundFile:
    path: str
    rows: list[tuple[str, str, float]] = field(default_factory=list)  # (isin, name, pct of fund)
    title: str = ""  # scheme name printed at the top of the file, when there is one

    @property
    def total_pct(self) -> float:
        return sum(p for _, _, p in self.rows)


def _num(v: object) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).replace(",", "").replace("%", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _table_rows(path: Path) -> list[list[object]]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as fh:
            return [list(r) for r in csv.reader(fh)]
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    best: list[list[object]] = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if len(rows) > len(best):
            best = rows
        for r in rows[:60]:  # prefer a sheet whose header row is recognisable
            if _find_cols(r)[0] is not None:
                return rows
    return best


def _find_cols(row: list[object]) -> tuple[int | None, int | None, int | None]:
    name = pct = isin = None
    for i, c in enumerate(row):
        t = str(c or "").strip()
        if not t:
            continue
        if isin is None and ISIN_HDR.search(t):
            isin = i
        elif pct is None and PCT_HDR.search(t):
            pct = i
        elif name is None and NAME_HDR.search(t):
            name = i
    return (name, pct, isin) if name is not None and pct is not None else (None, None, None)


def _title(top: list[list[object]]) -> str:
    """Scheme name from the rows above the header, e.g. 'JioBlackRock Flexi Cap Fund'."""
    for row in top:
        for c in row:
            t = str(c or "").strip()
            if (
                t
                and re.search(r"\bfund\b|\bscheme\b", t, re.I)
                and not re.search(r"portfolio|statement|as on", t, re.I)
            ):
                return t
    return ""


def read_fund_file(path: str | Path) -> FundFile:
    p = Path(path)
    table = _table_rows(p)
    for hi, row in enumerate(table[:80]):
        name_i, pct_i, isin_i = _find_cols(row)
        if name_i is None:
            continue
        out = FundFile(path=str(p), title=_title(table[:hi]))
        for r in table[hi + 1 :]:
            if name_i >= len(r) or pct_i >= len(r):
                continue
            name = str(r[name_i] or "").strip()
            pct = _num(r[pct_i])
            if (
                not name
                or pct is None
                or re.match(
                    r"(grand |sub )?total|net (current|assets|receivables)|inr cash|cash|collateral|tri.?party|treps",
                    name,
                    re.I,
                )
            ):
                continue
            isin = (
                str(r[isin_i]).strip().upper()
                if isin_i is not None and isin_i < len(r) and r[isin_i]
                else ""
            )
            out.rows.append((isin, name, pct))
        # some AMC files start with a row for the scheme itself at 100%: not a holding
        out.rows = [r for r in out.rows if not (not r[0] and r[2] >= 99.5)]
        if out.rows:
            if out.total_pct <= 1.5:  # weights given as fractions
                out.rows = [(i, n, p * 100) for i, n, p in out.rows]
            return out
    raise ValueError(f"{p.name}: no header row with a name column and a % to NAV column was found")


SECTION_EQUITY = re.compile(
    r"^(core equity|arbitrage and special situations|units issued by reits? (and|&) invits?)$", re.I
)
SECTION_OVERSEAS = re.compile(r"^overseas securities", re.I)
SECTION_OTHER = re.compile(
    r"^(debt and money market|certificate of deposit|commercial paper|t-bill|treasury bills?|mutual fund units|derivatives)",
    re.I,
)
LINE_PCT = re.compile(r"^(?P<name>.+?)\s+(?P<pct>\d+(?:\.\d+)?)%$")
OVERSEAS_ISIN = "XX-OVERSEAS"  # factsheets list no ISINs; this marks foreign holdings


def parse_factsheet_lines(lines: list[str], section: str, ff: FundFile) -> str:
    """Add the equity-like holdings found in one column of a factsheet page; returns the section reached."""
    for ln in lines:
        ln = ln.strip().lstrip("®@* ").strip()
        m = LINE_PCT.match(ln)
        head = (m.group("name") if m else ln).strip()
        if SECTION_OVERSEAS.match(head):
            section = "overseas"
        elif SECTION_EQUITY.match(head):
            section = "equity"
        elif SECTION_OTHER.match(head):
            section = "other"
        elif m and section in ("equity", "overseas"):
            if re.match(r"(sub )?total|net assets", head, re.I) or re.search(
                r"\(\d{2}/\d{2}/\d{4}\)", head
            ):
                continue
            ff.rows.append(
                (OVERSEAS_ISIN if section == "overseas" else "", head, float(m.group("pct")))
            )
    return section


def read_fund_pdf(path: str | Path) -> dict[str, FundFile]:
    """Fund-house factsheet PDF (for example PPFAS): every page with a 'Portfolio Data' table, grouped by
    scheme title. Pages are read column by column. Needs pdfplumber."""
    import pdfplumber

    p = Path(path)
    out: dict[str, FundFile] = {}
    with pdfplumber.open(p) as pdf:
        for page in pdf.pages:
            full = page.extract_text() or ""
            if "Portfolio Data" not in full:
                continue
            title = next((ln.strip() for ln in full.splitlines() if ln.strip()), p.stem)
            ff = out.setdefault(title, FundFile(path=f"{p.name} [{title}]"))
            w, h = page.width, page.height
            section = ""
            for box in ((0, 0, w / 2, h), (w / 2, 0, w, h)):
                section = parse_factsheet_lines(
                    (page.crop(box).extract_text() or "").splitlines(), section, ff
                )
    out = {k: v for k, v in out.items() if v.rows}
    if not out:
        raise ValueError(f"{p.name}: no 'Portfolio Data' table found in this PDF")
    return out


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in GENERIC}


def match_labels_to_funds(labels: list[str], funds: dict[str, str]) -> dict[str, str]:
    """funds: instrument_id -> fund name. Returns instrument_id -> label (file name or scheme title) with the
    best word overlap (at least 2 shared words, each label and fund used once)."""
    out: dict[str, str] = {}
    used: set[str] = set()
    scored = [
        (len(_tokens(lab) & _tokens(name)), lab, iid)
        for lab in labels
        for iid, name in funds.items()
    ]
    for score, lab, iid in sorted(scored, key=lambda x: -x[0]):
        if score >= 2 and iid not in out and lab not in used:
            out[iid] = lab
            used.add(lab)
    return out


def norm_key(name: str) -> str:
    """Comparable company key: the first two significant words ('Alphabet Inc. Class A' -> 'alphabet')."""
    toks = [t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in SUFFIX]
    return " ".join(toks[:2])


@dataclass
class Exposure:
    key: str
    name: str
    direct_inr: float
    via_funds_inr: float
    sources: list[tuple[str, float]]  # (fund name, inr)

    @property
    def total_inr(self) -> float:
        return self.direct_inr + self.via_funds_inr


def look_through(
    direct: dict[str, tuple[str, float]],  # instrument_id -> (name, value)
    fund_values: dict[str, tuple[str, float]],  # instrument_id -> (fund name, value)
    fund_files: dict[str, FundFile],
) -> tuple[list[Exposure], float, list[tuple[str, str, float]]]:
    """Returns (exposures per direct stock, INR held abroad through funds, pairwise fund overlaps)."""
    keys = {iid: (norm_key(n), n) for iid, (n, _) in direct.items()}
    by_isin = {iid: iid for iid in direct if re.match(r"^IN[A-Z0-9]{10}$", iid)}
    exp: dict[str, Exposure] = {
        iid: Exposure(k, n, direct[iid][1], 0.0, []) for iid, (k, n) in keys.items()
    }
    abroad = 0.0
    for fid, ff in fund_files.items():
        fname, fval = fund_values[fid]
        for isin, name, pct in ff.rows:
            inr = fval * pct / 100
            if isin and not isin.startswith("IN"):
                abroad += inr
            hit = by_isin.get(isin) if isin in by_isin else None
            if hit is None:
                k = norm_key(name)
                hit = next((iid for iid, (kk, _) in keys.items() if kk and kk == k), None)
            if hit:
                exp[hit].via_funds_inr += inr
                exp[hit].sources.append((fname, inr))
    pairs = []
    ids = list(fund_files)
    for i, a in enumerate(ids):
        wa = {(r[0] or norm_key(r[1])): r[2] for r in fund_files[a].rows}
        for b in ids[i + 1 :]:
            wb = {(r[0] or norm_key(r[1])): r[2] for r in fund_files[b].rows}
            common = sum(min(wa[k], wb[k]) for k in wa.keys() & wb.keys())
            pairs.append((fund_values[a][0], fund_values[b][0], common))
    exposures = sorted((e for e in exp.values() if e.via_funds_inr > 0), key=lambda e: -e.total_inr)
    return exposures, abroad, sorted(pairs, key=lambda x: -x[2])
