"""Fetch the primary documents behind each holding into data/inbox/research/<SYMBOL>/.

US: SEC EDGAR earnings releases (8-K item 2.02) and the MD&A of the latest 10-Q/10-K, fully automatic.
India: concall transcripts and results announcements whose links come from the stock's public Screener
page. The exchange often refuses automated downloads (HTTP 403). Those are never worked around: they are
listed in `TO_DOWNLOAD.txt` in the stock's folder, you save them from your browser into the same folder
(any name that starts with the date, `YYYY-MM-DD_`), and the next `thesis` run reads them.

Files are plain text with a source header, named `<published date>_<kind>_<ref>.txt`. A document already
fetched is skipped, so running this again is cheap.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from parakh_advisor.ingest.instruments import Instrument
from parakh_advisor.sources.http import Fetcher, SourceError, http_get
from parakh_advisor.sources.india.screener_docs import ScreenerDoc, choose, load_docs
from parakh_advisor.sources.india.transcripts import truncate_transcript, validate_transcript
from parakh_advisor.sources.text import cap_text, pdf_to_text
from parakh_advisor.sources.us.filings import EdgarFilings, FetchedDoc

TRANSCRIPT_CHARS = 25000
MAX_TRANSCRIPT_TRIES = 4
RESULTS_CHARS = 10000
MIN_USEFUL_CHARS = 1500


@dataclass
class SymbolReport:
    symbol: str
    written: list[str] = field(default_factory=list)
    already_had: int = 0
    to_download: list[tuple[str, str]] = field(default_factory=list)  # (suggested file name, url)
    notes: list[str] = field(default_factory=list)


def _ref(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:8]


def _write(folder: Path, doc: FetchedDoc, today: date) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{doc.published.isoformat()}_{doc.kind}_{doc.ref}.txt"
    header = (
        f"Source: {doc.url}\nDocument: {doc.kind}\nPublished: {doc.published}\nFetched: {today}\n\n"
    )
    (folder / name).write_text(header + doc.text, encoding="utf-8")
    return name


def _india_docs(
    inst: Instrument,
    cache: Path,
    fetch: Fetcher,
    doc_fetch: Fetcher,
    today: date,
    existing: set[str],
    rep: SymbolReport,
    sleep: Callable[[float], None],
) -> list[FetchedDoc]:
    code = inst.screener_code or inst.symbol
    if not code:
        rep.notes.append("no symbol or screener_code to look up on Screener")
        return []
    try:
        sleep(1.0)  # one page per company, with a pause between companies
        docs = load_docs(code, cache, fetch, today)
    except SourceError as exc:
        rep.notes.append(str(exc))
        return []
    out: list[FetchedDoc] = []
    # Transcripts: newest first; an unusable one is skipped and an older call tried instead.
    wanted, tried, got = 2, 0, []
    transcripts = sorted(
        (d for d in docs if d.kind == "transcript"), key=lambda d: d.when, reverse=True
    )
    for d in transcripts:
        if len(got) >= wanted or tried >= MAX_TRANSCRIPT_TRIES:
            break
        ref, suggested = _ref(d.url), _suggested(d)
        if suggested in existing or any(ref in n for n in existing):
            rep.already_had += 1
            got.append(d.when)
            continue
        tried += 1
        result = _download(d, doc_fetch, ref, rep, suggested)
        if result == "blocked":
            got.append(d.when)  # you will save it by hand; do not quietly substitute an older call
        elif result:
            out.append(result)
            got.append(d.when)
    calls = [d.when for d in docs if d.kind in ("transcript", "ppt")]
    if calls and got and max(calls) > max(got):
        rep.notes.append(
            f"newest concall ({max(calls):%b %Y}) has no usable transcript; newest used is "
            f"{max(got):%b %Y}, so treat the management commentary as stale"
        )
    elif calls and not got:
        rep.notes.append("concalls are listed but none has a usable transcript")
    for d in choose([x for x in docs if x.kind == "announcement"], transcripts=0):
        ref, suggested = _ref(d.url), _suggested(d)
        if suggested in existing or any(ref in n for n in existing):
            rep.already_had += 1
            continue
        result = _download(d, doc_fetch, ref, rep, suggested)
        if result and result != "blocked":
            out.append(result)
    return out


def _suggested(d: ScreenerDoc) -> str:
    return (
        f"{d.when.isoformat()}_{'concall-transcript' if d.kind == 'transcript' else 'results'}.pdf"
    )


def _download(
    d: ScreenerDoc, fetch: Fetcher, ref: str, rep: SymbolReport, suggested: str
) -> FetchedDoc | str | None:
    """A FetchedDoc, "blocked" (listed for manual download) or None (unusable)."""
    try:
        raw = fetch(d.url)
    except SourceError as exc:
        rep.to_download.append((suggested, d.url))
        rep.notes.append(f"{d.when} {d.title[:60]}: not downloaded ({exc})")
        return "blocked"
    try:
        text = pdf_to_text(raw) if raw[:4] == b"%PDF" else raw.decode("utf-8", "replace")
    except Exception as exc:  # a damaged or unusual PDF must not stop the other documents
        rep.notes.append(f"{d.when} {d.title[:60]}: could not read the file ({exc})")
        return None
    is_call = d.kind == "transcript"
    if is_call:
        check = validate_transcript(text)
        if not check.ok:
            rep.notes.append(f"{d.when} transcript rejected: {'; '.join(check.reasons)}")
            return None
    elif len(text) < MIN_USEFUL_CHARS:
        rep.notes.append(f"{d.when} {d.title[:60]}: almost no text (scanned image?), skipped")
        return None
    if is_call:
        return FetchedDoc(
            d.when, "concall-transcript", d.url, truncate_transcript(text, TRANSCRIPT_CHARS), ref
        )
    return FetchedDoc(d.when, "results", d.url, cap_text(text, RESULTS_CHARS), ref)


def fetch_all(
    instruments: dict[str, Instrument],
    research_dir: str | Path = "data/inbox/research",
    cache_dir: str | Path = "data/cache",
    only: str | None = None,
    fetch: Fetcher = http_get,
    today: date | None = None,
    doc_fetch: Fetcher | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[SymbolReport]:
    today = today or date.today()
    root, cache = Path(research_dir), Path(cache_dir)
    reports: list[SymbolReport] = []
    edgar = EdgarFilings(cache, fetch)
    for iid, inst in instruments.items():
        symbol = inst.symbol or iid
        if only and only.upper() not in symbol.upper():
            continue
        if not (inst.edgar or inst.screener or inst.screener_code):
            continue
        rep = SymbolReport(symbol)
        folder = root / symbol
        existing = {p.name for p in folder.iterdir()} if folder.is_dir() else set()
        try:
            if inst.edgar:
                docs, notes = edgar.documents(inst.edgar, today)
                rep.notes += notes
                fresh = []
                for d in docs:
                    if any(d.ref in n for n in existing):
                        rep.already_had += 1
                    else:
                        fresh.append(d)
            else:
                fresh = _india_docs(
                    inst, cache, fetch, doc_fetch or fetch, today, existing, rep, sleep
                )
        except SourceError as exc:
            rep.notes.append(str(exc))
            fresh = []
        except Exception as exc:  # one stock's odd page must not stop the others
            rep.notes.append(f"unexpected error, skipped: {type(exc).__name__}: {exc}")
            fresh = []
        for d in fresh:
            rep.written.append(_write(folder, d, today))
        _write_todo(folder, rep)
        reports.append(rep)
    return reports


def _write_todo(folder: Path, rep: SymbolReport) -> None:
    path = folder / "TO_DOWNLOAD.txt"
    if not rep.to_download:
        if path.exists():
            path.unlink()
        return
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{rep.symbol}: the exchange refused automated downloads of these documents.",
        "Open each link in your browser and save the file in this folder with the suggested name.",
        "The date at the start of the name is what counts as the document's publication date.",
        "",
    ]
    for name, url in rep.to_download:
        lines += [f"{name}", f"  {url}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
