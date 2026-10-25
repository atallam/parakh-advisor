"""Document fetching, offline: Screener page parsing, EDGAR-free orchestration, the manual-download list."""

from datetime import date
from pathlib import Path

from parakh_advisor.ingest.instruments import Instrument
from parakh_advisor.research.fetch import fetch_all
from parakh_advisor.sources.http import SourceError
from parakh_advisor.sources.india.screener_docs import choose, parse_page
from parakh_advisor.sources.text import cap_text, html_to_text

TODAY = date(2026, 10, 24)
PAGE = """
<html><body><div id="documents"><h3>Concalls</h3>
<ul class="list-links">
<li><div class="ink-600 font-size-15 nowrap">Jul 2026</div>
<a class="concall-link" href="https://www.bseindia.com/t1.pdf">Transcript</a></li>
<li><div class="ink-600 font-size-15 nowrap">Apr 2026</div>
<a class="concall-link" href="https://www.bseindia.com/t0.pdf">Transcript</a></li>
</ul></div></body></html>
"""
LONG = ("Management said demand stayed strong this quarter and margins improved. " * 60).encode()


def test_parse_page_dates_transcripts_at_month_end():
    docs = parse_page(PAGE, TODAY)
    assert {d.kind for d in docs} == {"transcript"}
    assert sorted(d.when for d in docs) == [date(2026, 4, 30), date(2026, 7, 31)]
    assert len(choose(docs)) == 2


def test_html_to_text_and_cap():
    text = html_to_text("<html><body><p>Revenue grew.</p><script>x=1</script></body></html>")
    assert "Revenue grew." in text and "x=1" not in text
    assert len(cap_text("word " * 1000, 100)) <= 140


def _india(tmp_path, fetch):
    inst = {"IN:X": Instrument(symbol="X", screener="X Ltd")}
    return fetch_all(
        inst, tmp_path / "r", tmp_path / "c", fetch=fetch, today=TODAY, sleep=lambda s: None
    )


def test_downloads_and_skips_on_second_run(tmp_path: Path):
    def fetch(url: str) -> bytes:
        if "screener.in" in url:
            return PAGE.encode()
        return LONG

    first = _india(tmp_path, fetch)[0]
    assert len(first.written) == 2 and not first.to_download
    files = sorted(p.name for p in (tmp_path / "r" / "X").iterdir())
    assert files[0].startswith("2026-04-30_")
    text = (tmp_path / "r" / "X" / files[0]).read_text(encoding="utf-8")
    assert text.startswith("Source: https://www.bseindia.com/")
    second = _india(tmp_path, fetch)[0]
    assert second.written == [] and second.already_had == 2


def test_blocked_exchange_lists_manual_downloads(tmp_path: Path):
    def fetch(url: str) -> bytes:
        if "screener.in" in url:
            return PAGE.encode()
        raise SourceError("HTTP 403")

    rep = _india(tmp_path, fetch)[0]
    assert rep.written == [] and len(rep.to_download) == 2
    todo = (tmp_path / "r" / "X" / "TO_DOWNLOAD.txt").read_text(encoding="utf-8")
    assert "2026-07-31_concall-transcript.pdf" in todo and "t1.pdf" in todo


def test_short_documents_are_skipped(tmp_path: Path):
    def fetch(url: str) -> bytes:
        return PAGE.encode() if "screener.in" in url else b"too short"

    rep = _india(tmp_path, fetch)[0]
    assert rep.written == [] and rep.notes


def test_announcement_without_closing_div_does_not_crash():
    html = (
        '<h3>Announcements</h3><ul><li><a href="https://x/y.pdf">Financial Results'
        '<div class="ink-600"><time datetime="2026-10-20T10:00">20 Oct</time>'
        "</a></li></ul>"
    )
    docs = parse_page(html, TODAY)
    assert len(docs) == 1 and docs[0].when == date(2026, 10, 20)


def test_validator_rejects_cover_pages_and_garbled_text():
    from parakh_advisor.sources.india.transcripts import truncate_transcript, validate_transcript

    assert validate_transcript(LONG.decode()).ok
    assert not validate_transcript("Cover page. " * 50).ok
    bad = validate_transcript(("é" * 3000) + " management quarter margin")
    assert not bad.ok and any("unreadable" in r for r in bad.reasons)
    text = "intro " * 100 + "Question and Answer session " + "qa " * 5000
    cut = truncate_transcript(text, 3000)
    assert len(cut) <= 3000 and "Question and Answer" in cut


PAGE3 = PAGE.replace(
    "</ul>",
    '<li><div class="ink-600 font-size-15 nowrap">Jan 2026</div>'
    '<a class="concall-link" href="https://www.bseindia.com/t_1.pdf">Transcript</a></li></ul>',
)


def test_bad_newest_transcript_falls_back_to_older_and_flags_stale(tmp_path: Path):
    def fetch(url: str) -> bytes:
        if "screener.in" in url:
            return PAGE3.encode()
        return b"Cover page only. " if url.endswith("t1.pdf") else LONG

    rep = _india(tmp_path, fetch)[0]
    names = sorted(p.name for p in (tmp_path / "r" / "X").iterdir())
    assert len(rep.written) == 2 and names[0].startswith("2026-01-31_")
    assert not any(n.startswith("2026-07-31_") for n in names)
    assert any("rejected" in n for n in rep.notes)
    assert any("stale" in n for n in rep.notes)


def test_browser_headers_apply_only_to_document_downloads(tmp_path: Path):
    seen = {"page": 0, "doc": 0}

    def fetch(url: str) -> bytes:
        seen["page"] += 1
        return PAGE.encode()

    def doc_fetch(url: str) -> bytes:
        seen["doc"] += 1
        return LONG

    inst = {"IN:X": Instrument(symbol="X", screener="X Ltd")}
    fetch_all(
        inst, tmp_path / "r", tmp_path / "c", fetch=fetch, doc_fetch=doc_fetch,
        today=TODAY, sleep=lambda s: None,
    )  # fmt: skip
    assert seen == {"page": 1, "doc": 2}
