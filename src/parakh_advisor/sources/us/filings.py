"""US filings from SEC EDGAR: the latest earnings releases (8-K item 2.02, exhibit 99) and the
management's-discussion section of the latest 10-Q or 10-K, as plain text.

These are the primary documents behind the numbers, so a thesis that cites them can be MEDIUM confidence
instead of numbers-only. Nothing here is scraped: it uses the same official endpoints (and the same
descriptive User-Agent, set PARAKH_CONTACT) as the fundamentals loader.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from parakh_advisor.sources.http import Fetcher, SourceError, get_json, http_get
from parakh_advisor.sources.text import cap_text, extract_section, html_to_text
from parakh_advisor.sources.us.edgar import Edgar

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{name}"
EXHIBIT_99 = re.compile(r"(ex[-_]?99|exhibit[-_]?99)", re.I)

RELEASE_CHARS = 14000
MDA_CHARS = 20000
MAX_RELEASES = 3
LOOKBACK_DAYS = 400


@dataclass
class FetchedDoc:
    """One document ready to be written into data/inbox/research/<SYMBOL>/."""

    published: date
    kind: str  # earnings-release | mda-10q | mda-10k | concall-transcript | results
    url: str
    text: str
    ref: str  # short stable id used in the file name and to skip documents already fetched


def _mda_patterns(form: str) -> tuple[str, str]:
    """(start, end) regex for the MD&A heading of a 10-Q (item 2) or a 10-K (item 7)."""
    if form == "10-K":
        return (
            r"item\s*7\.?\s*management's\s+discussion\s+and\s+analysis",
            r"item\s*7a\.?\s*quantitative|item\s*8\.?\s*financial\s+statements",
        )
    return (
        r"item\s*2\.?\s*management's\s+discussion\s+and\s+analysis",
        r"item\s*3\.?\s*quantitative|item\s*4\.?\s*controls",
    )


def _strip_exhibit_header(text: str) -> str:
    """Drop the 'EX-99.1 / 3 / file.htm / EX-99.1' lines that sit above the headline of an exhibit."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and (
        not lines[i].strip()
        or re.fullmatch(r"ex[-_ ]?99(\.\d+)?|\d{1,2}|.*\.html?", lines[i].strip(), re.I)
    ):
        i += 1
    return "\n".join(lines[i:]).strip()


class EdgarFilings:
    def __init__(self, cache_dir: str | Path = "data/cache", fetch: Fetcher = http_get):
        self.cache = Path(cache_dir)
        self.fetch = fetch
        self.edgar = Edgar(cache_dir, fetch)

    def _submissions(self, cik: int, max_age_days: int = 1) -> dict:
        path = self.cache / f"edgar_sub_{cik}.json"
        if (
            path.exists()
            and (datetime.now().timestamp() - path.stat().st_mtime) < max_age_days * 86400
        ):
            return json.loads(path.read_text(encoding="utf-8"))
        data = get_json(SUBMISSIONS_URL.format(cik=cik), self.fetch)
        self.cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    @staticmethod
    def pick(sub: dict, today: date) -> tuple[list[dict], dict | None]:
        """(earnings-release 8-Ks newest first, latest 10-Q/10-K) from a submissions document."""
        r = sub.get("filings", {}).get("recent", {})
        rows = [
            {
                k: r[k][i]
                for k in ("form", "filingDate", "items", "accessionNumber", "primaryDocument")
            }
            for i in range(len(r.get("form", [])))
        ]
        oldest = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
        releases = [
            x
            for x in rows
            if x["form"] == "8-K" and "2.02" in x["items"].split(",") and x["filingDate"] >= oldest
        ]
        releases.sort(key=lambda x: x["filingDate"], reverse=True)
        periodic = [x for x in rows if x["form"] in ("10-Q", "10-K")]
        periodic.sort(key=lambda x: x["filingDate"], reverse=True)
        return releases[:MAX_RELEASES], (periodic[0] if periodic else None)

    def _exhibit_name(self, cik: int, acc_nodash: str) -> str | None:
        idx = json.loads(self.fetch(INDEX_URL.format(cik=cik, acc=acc_nodash)))
        names = [i["name"] for i in idx.get("directory", {}).get("item", [])]
        hits = [n for n in names if EXHIBIT_99.search(n) and n.lower().endswith((".htm", ".html"))]
        return hits[0] if hits else None

    def documents(
        self, ticker: str, today: date | None = None
    ) -> tuple[list[FetchedDoc], list[str]]:
        """Fetch what is available. Returns (documents, notes about anything that could not be read)."""
        today = today or date.today()
        cik = self.edgar.cik(ticker)
        releases, periodic = self.pick(self._submissions(cik), today)
        docs: list[FetchedDoc] = []
        notes: list[str] = []
        for x in releases:
            acc = x["accessionNumber"].replace("-", "")
            try:
                name = self._exhibit_name(cik, acc)
                if not name:
                    notes.append(f"{x['filingDate']} 8-K: no exhibit 99 found")
                    continue
                url = DOC_URL.format(cik=cik, acc=acc, name=name)
                body = cap_text(_strip_exhibit_header(html_to_text(self.fetch(url))), RELEASE_CHARS)
            except (SourceError, ValueError, KeyError) as exc:
                notes.append(f"{x['filingDate']} 8-K: {exc}")
                continue
            if len(body) > 500:
                docs.append(
                    FetchedDoc(
                        date.fromisoformat(x["filingDate"]), "earnings-release", url, body, acc[-8:]
                    )
                )
        if periodic:
            acc = periodic["accessionNumber"].replace("-", "")
            url = DOC_URL.format(cik=cik, acc=acc, name=periodic["primaryDocument"])
            try:
                text = html_to_text(self.fetch(url))
                start, end = _mda_patterns(periodic["form"])
                mda = extract_section(text, start, end, limit=MDA_CHARS)
                if mda:
                    kind = "mda-10k" if periodic["form"] == "10-K" else "mda-10q"
                    docs.append(
                        FetchedDoc(
                            date.fromisoformat(periodic["filingDate"]), kind, url, mda, acc[-8:]
                        )
                    )
                else:
                    notes.append(
                        f"{periodic['filingDate']} {periodic['form']}: MD&A section not found"
                    )
            except (SourceError, ValueError) as exc:
                notes.append(f"{periodic['filingDate']} {periodic['form']}: {exc}")
        return docs, notes
