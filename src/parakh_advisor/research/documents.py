"""Researcher (v1): turn documents you supply into citable evidence passages.

Drop results press releases, call transcripts or filings for a stock into
`data/inbox/research/<SYMBOL>/` as .txt, .md or .pdf. Name them `YYYY-MM-DD_anything.ext`; the date is
when the document was published and is what lets a later thesis change count as "new evidence".
Each document is split into passages with stable ids (`DOC.<SYMBOL>.<hash>.p<n>`), so the Analyst can
cite them and code can check a quote really appears in the passage cited.
`parakh-advisor fetch-docs` fills the same folder automatically (EDGAR for US; Screener-listed transcripts and
results for India, with a TO_DOWNLOAD.txt for anything the exchange refuses to serve to a program).
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

from parakh_advisor.thesis.evidence import Evidence

PASSAGE_CHARS = 1100
MAX_PASSAGES = 60  # per stock, newest documents first: keeps the prompt bounded


def _read(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from parakh_advisor.sources.text import pdf_to_text

        return pdf_to_text(path.read_bytes())
    return path.read_text(encoding="utf-8", errors="replace")


def _doc_date(path: Path) -> date:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    if m:
        return date.fromisoformat(m.group(1))
    return datetime.fromtimestamp(path.stat().st_mtime).date()  # fallback: file date, less reliable


def split_passages(text: str, size: int = PASSAGE_CHARS) -> list[str]:
    """Paragraph-aware chunks of about `size` characters."""
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    out: list[str] = []
    cur = ""
    for p in filter(None, paras):
        while len(p) > size:  # very long paragraph: hard split
            out.append(p[:size])
            p = p[size:]
        if len(cur) + len(p) + 1 > size and cur:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        out.append(cur)
    return out


def load_documents(root: str | Path, symbol: str) -> list[Evidence]:
    folder = Path(root) / symbol
    if not folder.is_dir():
        return []
    files = sorted(
        (f for f in folder.iterdir() if f.suffix.lower() in {".txt", ".md", ".pdf"}),
        key=_doc_date,
        reverse=True,
    )
    items: list[Evidence] = []
    for f in files:
        text = _read(f)
        h = hashlib.sha256(text.encode()).hexdigest()[:6]
        d = _doc_date(f)
        for n, passage in enumerate(split_passages(text), 1):
            items.append(
                Evidence(
                    id=f"DOC.{symbol}.{h}.p{n}", kind="filing", text=passage, as_of=d, source=f.name
                )
            )
    return items[:MAX_PASSAGES]
