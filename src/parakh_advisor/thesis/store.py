"""Append-only thesis store: data/theses/<instrument>/v0001.json. Versions are never edited."""

from __future__ import annotations

import re
from pathlib import Path

from parakh_advisor.thesis.models import Thesis


class ThesisStore:
    def __init__(self, root: str | Path = "data/theses", names: dict[str, str] | None = None):
        """`names` maps instrument id (ISIN or US:TICKER) to a readable folder name (the symbol)."""
        self.root = Path(root)
        self.names = names or {}

    @staticmethod
    def _safe(text: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", text)

    def _dir(self, instrument_id: str) -> Path:
        legacy = self.root / self._safe(instrument_id)
        name = self.names.get(instrument_id)
        if not name:
            return legacy
        d = self.root / self._safe(name)
        if legacy.exists() and not d.exists():
            legacy.rename(d)  # one-time move of an older id-named folder; content untouched
        return d

    def latest(self, instrument_id: str) -> Thesis | None:
        d = self._dir(instrument_id)
        files = sorted(d.glob("v*.json")) if d.exists() else []
        return Thesis.model_validate_json(files[-1].read_text(encoding="utf-8")) if files else None

    def history(self, instrument_id: str) -> list[Thesis]:
        d = self._dir(instrument_id)
        return (
            [
                Thesis.model_validate_json(f.read_text(encoding="utf-8"))
                for f in sorted(d.glob("v*.json"))
            ]
            if d.exists()
            else []
        )

    def save(self, t: Thesis) -> Path:
        d = self._dir(t.instrument_id)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"v{t.version:04d}.json"
        if path.exists():
            raise FileExistsError(f"{path} exists; theses are immutable")
        path.write_text(t.model_dump_json(indent=2), encoding="utf-8")
        return path
