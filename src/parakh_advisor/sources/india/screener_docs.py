"""Document links for an Indian listing, read from its public Screener company page.

The page lists concall transcripts / presentations and exchange announcements with dates. Only the
links are taken from Screener (the page is public and Screener's robots.txt allows /company/ pages; it
is fetched once per company, cached for a day, with a pause between companies). The documents themselves
are hosted by the exchange or the company, and the exchange often refuses automated downloads. Those
refusals are reported, never worked around: the report lists them so you can open them in your browser and
save them into the research folder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from parakh_advisor.sources.http import Fetcher, SourceError, http_get

PAGE_URLS = (
    "https://www.screener.in/company/{code}/consolidated/",
    "https://www.screener.in/company/{code}/",
)
KEEP = re.compile(r"financial results|outcome of board|press release|earnings|results", re.I)
DROP = re.compile(
    r"intimation|schedule|newspaper|trading window|certificate|record date|loss of share|"
    r"duplicate|analyst / investor meet|clarification|credit rating|shareholding",
    re.I,
)
MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


@dataclass
class ScreenerDoc:
    kind: str  # transcript | ppt | announcement
    when: date
    title: str
    url: str


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).replace("&amp;", "&").strip()


def _month_end(label: str, today: date) -> date:
    mon, year = label.split()
    m, y = MONTHS[mon], int(year)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    end = date.fromordinal(nxt.toordinal() - 1)
    return min(end, today)


def parse_page(html: str, today: date | None = None) -> list[ScreenerDoc]:
    today = today or date.today()
    docs: list[ScreenerDoc] = []
    parts = re.split(r"(?=<h3\b)", html)
    for part in parts:
        head = re.match(r"<h3[^>]*>\s*([^<]+?)\s*</h3>", part)
        if not head:
            continue
        name = head.group(1).lower()
        if name.startswith("concalls"):
            for li in re.split(r"(?=<li\b)", part)[1:]:
                label = re.search(r"\b([A-Z][a-z]{2} \d{4})\b", li[:600])
                if not label or label.group(1).split()[0] not in MONTHS:
                    continue
                when = _month_end(label.group(1), today)
                for attrs, inner in re.findall(r"<a\b([^>]*)>(.*?)</a>", li, re.S):
                    href = re.search(r'href="([^"]+)"', attrs)
                    text = _strip(inner).lower()
                    if href and text in ("transcript", "ppt"):
                        docs.append(
                            ScreenerDoc(
                                "transcript" if text == "transcript" else "ppt",
                                when,
                                f"Concall {text} {label.group(1)}",
                                href.group(1).replace("&amp;", "&"),
                            )
                        )
        elif name.startswith("announcements"):
            for li in re.split(r"(?=<li\b)", part)[1:]:
                a = re.search(r"<a\b([^>]*)>(.*?)</a>", li, re.S)
                t = re.search(r'datetime="(\d{4}-\d{2}-\d{2})', li)
                href = re.search(r'href="([^"]+)"', a.group(1)) if a else None
                if not (a and t and href):
                    continue
                title = _strip(re.sub(r'<div class="ink-600.*', "", a.group(2), flags=re.S))
                m = re.search(r"</time>\s*-?\s*(.*?)(?:</div>|</li>|$)", li, re.S)
                desc = _strip(m.group(1)) if m else ""
                docs.append(
                    ScreenerDoc(
                        "announcement",
                        datetime.strptime(t.group(1), "%Y-%m-%d").date(),
                        f"{title} - {desc}" if desc else title,
                        href.group(1).replace("&amp;", "&"),
                    )
                )
    return docs


def choose(docs: list[ScreenerDoc], transcripts: int = 2, results: int = 2) -> list[ScreenerDoc]:
    """Newest concall transcripts, plus the newest results announcements (not mere intimations)."""
    tr = sorted((d for d in docs if d.kind == "transcript"), key=lambda d: d.when, reverse=True)
    rs = sorted(
        (
            d
            for d in docs
            if d.kind == "announcement" and KEEP.search(d.title) and not DROP.search(d.title)
        ),
        key=lambda d: d.when,
        reverse=True,
    )
    return tr[:transcripts] + rs[:results]


def load_docs(
    code: str,
    cache_dir: str | Path = "data/cache",
    fetch: Fetcher = http_get,
    today: date | None = None,
    max_age_days: int = 1,
) -> list[ScreenerDoc]:
    cache = Path(cache_dir)
    path = cache / f"screener_page_{re.sub(r'[^A-Za-z0-9]+', '_', code)}.html"
    if path.exists() and (datetime.now().timestamp() - path.stat().st_mtime) < max_age_days * 86400:
        html = path.read_text(encoding="utf-8")
    else:
        html, last = "", None
        for tpl in PAGE_URLS:
            try:
                html = fetch(tpl.format(code=quote(code, safe="&"))).decode("utf-8", "replace")
                break
            except SourceError as exc:
                last = exc
        if not html:
            raise SourceError(f"Screener page for {code} could not be read ({last})")
        cache.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    return parse_page(html, today)
