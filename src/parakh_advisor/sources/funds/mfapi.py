"""Resolve a mutual fund / ETF scheme by AMFI scheme code through mfapi.in (community mirror of AMFI).

Gives the real scheme name, SEBI category, fund house and plan. Results are cached on disk, so a
normal run makes no network calls once a fund has been seen.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from parakh_advisor.sources.http import Fetcher, SourceError, get_json, http_get

MFAPI_URL = "https://api.mfapi.in/mf/{code}"


class FundMeta(BaseModel):
    scheme_code: str
    scheme_name: str
    category: str  # e.g. "Equity Scheme - Small Cap Fund", "Other Scheme - Gold ETF"
    fund_house: str
    plan: str | None  # "Direct" | "Regular" | None

    @property
    def is_commodity(self) -> bool:
        c = self.category.lower()
        return "gold" in c or "silver" in c or "commodit" in c

    @property
    def short_category(self) -> str:
        """`Equity Scheme - Small Cap Fund` -> `Small Cap Fund`."""
        return self.category.split(" - ", 1)[-1].strip()


def _plan(name: str) -> str | None:
    n = name.lower()
    if "direct" in n:
        return "Direct"
    if "regular" in n:
        return "Regular"
    return None


def parse_meta(code: str, payload: dict) -> FundMeta:
    meta = payload.get("meta") or {}
    name = str(meta.get("scheme_name") or "").strip()
    if not name:
        raise SourceError(f"mfapi returned no scheme_name for {code}")
    return FundMeta(
        scheme_code=str(code),
        scheme_name=name,
        category=str(meta.get("scheme_category") or "Unknown"),
        fund_house=str(meta.get("fund_house") or "Unknown"),
        plan=_plan(name),
    )


class MfapiResolver:
    def __init__(self, cache_dir: str | Path = "data/cache", fetch: Fetcher = http_get):
        self.cache_dir = Path(cache_dir)
        self.fetch = fetch

    def __call__(self, scheme_code: str) -> FundMeta | None:
        code = str(scheme_code).strip()
        if not code:
            return None
        cached = self.cache_dir / f"mfapi_{code}.json"
        if cached.exists():
            return FundMeta.model_validate_json(cached.read_text(encoding="utf-8"))
        try:
            meta = parse_meta(code, get_json(MFAPI_URL.format(code=code), self.fetch))
        except SourceError:
            return None  # leave the fund unresolved; DQ-06 will say so
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(meta.model_dump()), encoding="utf-8")
        return meta
