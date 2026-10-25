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
    """Scheme name from the rows above the header, e.g. 'JioBlackRock Flexi Cap Fund'.

    Prefers the cell after a "Scheme name" label (SBI), skips AMC-only names such as 'INVESCO MUTUAL FUND',
    and keeps only the first line of a multi-line cell (Invesco puts a description under the name)."""
    fallback = ""
    for row in top:
        cells = [str(c or "").strip() for c in row]
        for i, t in enumerate(cells):
            if re.match(r"scheme name\b", t, re.I):
                nxt = next((c for c in cells[i + 1 :] if c), "")
                if nxt:
                    return nxt.splitlines()[0].strip()
        for t in cells:
            first = t.splitlines()[0].strip() if t else ""
            if (
                first
                and re.search(r"\bfund\b|\bscheme\b", first, re.I)
                and not re.search(r"portfolio|statement|as on", first, re.I)
            ):
                if re.fullmatch(r"[\w&.\- ]*mutual fund", first, re.I) and len(first.split()) <= 4:
                    fallback = fallback or first  # the AMC, not the scheme
                    continue
                return first
    return fallback


ISIN_OK = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
NON_EQUITY_NAME = re.compile(
    r"t-?bills?\b|\bcall option|\bput option|\bindex\b.*\d{2}[-./]\d{2}[-./]\d{4}|margin amount|derivatives? total"
    r"|net receivable|net payable|\(short\)|^short\b|^long\b",
    re.I,
)


def _drop_non_equity(
    rows: list[tuple[str, str, float]], has_isin: bool
) -> list[tuple[str, str, float]]:
    """Keep equity lines only. AMC sheets also list T-bills, index futures, options, margin money and, further
    down, side tables (derivative expiry dates, quantities) whose numbers look like weights. When the file has an
    ISIN column, a line with an ISIN cell must hold a real ISIN, and government-security ISINs (IN00...) and negative weights
    (short or option positions) are dropped."""
    keep = []
    for isin, name, pct in rows:
        if pct <= 0 or NON_EQUITY_NAME.search(name):
            continue
        if has_isin and isin and (not ISIN_OK.match(isin) or isin.startswith("IN0")):
            continue
        keep.append((isin, name, pct))
    return keep


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
        out.rows = _drop_non_equity(out.rows, has_isin=isin_i is not None)
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


PCT_TOKEN = re.compile(
    r"^-?\d+\.\d{2}%$"
)  # table figures have two decimals; chart ticks ("30.0%") do not
NAV_STOP = re.compile(r"^(net cash|net current|cash and|cash &|grand total)\b", re.I)
LIGATURE = re.compile(r"(?<=\w) (ffi|ff|fi|fl) (?=\w)")


def parse_nav_columns(words: list[dict], page_width: float) -> list[tuple[str, str, float]]:
    """One page of a 'Name of the Instrument | % to NAV' portfolio laid out in two or three side-by-side
    columns (Bandhan). `words` are pdfplumber words with x0, x1, top, text and fontname. Columns are found
    from the right edges of the percentage figures (they line up within a column). Industry headings are bold
    and carry the sum of their stocks, so they are skipped; names that wrap onto two lines are joined; PDF
    ligature gaps ('Scienti fi c') are closed. Cash and grand-total lines are skipped; the chart printed below
    the table is ignored because its figures have one decimal."""
    pct_words = [w for w in words if PCT_TOKEN.match(w["text"])]
    edges: list[float] = []
    for x in sorted(w["x1"] for w in pct_words):
        if not edges or x - edges[-1] > 8:
            edges.append(x)
    if not edges:
        return []
    header_top = min((w["top"] for w in words if w["text"] == "Name"), default=-1.0)
    words = [
        w for w in words if w["top"] > header_top + 2.5
    ]  # drop the page title and column headers
    rows: list[tuple[str, str, float]] = []
    prev_edge = -1.0
    for edge in edges:
        col = [w for w in words if prev_edge + 3 < w["x1"] <= edge + 3]
        prev_edge = edge
        col.sort(key=lambda w: (w["top"], w["x0"]))
        lines: list[list[dict]] = []
        for w in col:  # cluster into visual lines (tops within 2.5 points)
            if lines and abs(lines[-1][0]["top"] - w["top"]) <= 2.5:
                lines[-1].append(w)
            else:
                lines.append([w])
        buf: list[dict] = []
        for ln in lines:
            ln.sort(key=lambda w: w["x0"])
            pct_w = next((w for w in ln if PCT_TOKEN.match(w["text"])), None)
            name_w = [w for w in ln if w is not pct_w]
            if pct_w is None:
                buf += name_w
                continue
            parts = buf + name_w
            buf = []
            bold = bool(parts) and any("bold" in w.get("fontname", "").lower() for w in parts)
            name = LIGATURE.sub(r"\1", " ".join(w["text"] for w in parts)).strip()
            name = re.sub(r"\s+", " ", name)
            name = re.sub(
                r"^.*?name of the instrument\s*(% to nav)?\s*", "", name, flags=re.I
            )  # page heading text sharing the first line
            if not name or bold or NAV_STOP.match(name):
                continue
            rows.append(("", name, float(pct_w["text"][:-1])))
    return rows


def read_nav_columns_pdf(path: str | Path) -> dict[str, FundFile]:
    """Single-scheme monthly portfolio PDF with a '% to NAV' table in side-by-side columns. The scheme name is
    the first line mentioning 'Fund' on page 1."""
    import pdfplumber

    p = Path(path)
    with pdfplumber.open(p) as pdf:
        first = (pdf.pages[0].extract_text() or "").splitlines() if pdf.pages else []
        title = next((ln.strip() for ln in first if re.search(r"\bfund\b", ln, re.I)), p.stem)
        ff = FundFile(path=p.name, title=title)
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not re.search(r"name of the instrument", text, re.I) or "% to NAV" not in text:
                continue
            words = page.extract_words(extra_attrs=["fontname"])
            ff.rows += parse_nav_columns(words, float(page.width))
    ff.rows = [r for r in ff.rows if not re.fullmatch(r"(equity|reit)", r[1], re.I)]
    if not ff.rows:
        raise ValueError(f"{p.name}: no 'Portfolio Data' or '% to NAV' table found in this PDF")
    return {title: ff}


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
    if not out:  # not a factsheet: try a single-scheme '% to NAV' portfolio laid out in columns
        return read_nav_columns_pdf(p)
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
            indian_isin = bool(re.match(r"^IN[A-Z0-9]{10}$", isin))
            if hit is None and not indian_isin:
                # An Indian ISIN that is not one of your holdings is a different company, whatever its name
                # (Mahindra & Mahindra Financial Services is not Mahindra & Mahindra), so names are matched
                # only for lines with no ISIN, a foreign ISIN, or the overseas marker.
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
