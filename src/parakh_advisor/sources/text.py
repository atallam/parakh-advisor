"""Turn fetched filings (HTML, PDF) into plain text the Researcher can split into citable passages.

Tables keep their rows (cells joined with " | ") because the numbers in a results release live in them.
Everything here is deterministic and offline; fetching is somebody else's job.
"""

from __future__ import annotations

import io
import re
from html.parser import HTMLParser

_BLOCK = {
    "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section",
    "article", "header", "footer", "blockquote", "pre",
}  # fmt: skip
_SKIP = {"script", "style", "head", "ix:header", "title"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag in _BLOCK and self._cell is None:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            if self._row is not None and text:
                self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.out.append("\n" + " | ".join(self._row))
            self._row = None
        elif tag in _BLOCK and self._cell is None:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        (self._cell if self._cell is not None else self.out).append(data)


def html_to_text(html: bytes | str) -> str:
    raw = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    p = _Text()
    p.feed(raw)
    text = "".join(p.out).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def pdf_to_text(data: bytes, max_pages: int = 40) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [(p.extract_text() or "") for p in pdf.pages[:max_pages]]
    return "\n\n".join(pages).strip()


def cap_text(text: str, limit: int) -> str:
    """First `limit` characters, cut at a paragraph or sentence end where one is close to the limit."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("\n\n", "\n", ". "):
        i = cut.rfind(sep)
        if i > limit * 0.7:
            return cut[: i + len(sep)].rstrip()
    return cut


_APOS = "['’‘`]"


def extract_section(
    text: str, start: str, end: str, min_len: int = 3000, limit: int = 20000
) -> str:
    """The longest stretch that begins at a `start` heading and runs to the next `end` heading. The table of
    contents also matches `start`, but its span is short, so requiring `min_len` skips it."""
    s_re = re.compile(start.replace("'", _APOS), re.I)
    e_re = re.compile(end.replace("'", _APOS), re.I)
    best = ""
    for m in s_re.finditer(text):
        e = e_re.search(text, m.end())
        span = text[m.start() : e.start() if e else len(text)]
        if len(span) > len(best):
            best = span
    return cap_text(best, limit) if len(best) >= min_len else ""
