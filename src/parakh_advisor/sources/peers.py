"""Peer groups: who each holding is compared with.

config/peers.yaml:
    semis:    {market: US, members: [AVGO, QCOM, TXN, MU]}            # tickers; EDGAR + Yahoo price
    in_auto:  {market: IN, dir: data/inbox/peers/in_auto}             # Screener exports you save there
    banks:    {market: US, profile: bank, members: [JPM, WFC]}

A holding names its group with `peer_group:` in instruments.yaml. Peers that cannot be loaded are
skipped with a message, never silently; the group size is shown with every percentile.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import BaseModel

from parakh_advisor.metrics.quality import CompanyMetrics, compute
from parakh_advisor.sources.http import SourceError
from parakh_advisor.sources.india.screener_export import load_folder
from parakh_advisor.sources.us.edgar import Edgar
from parakh_advisor.sources.us.prices import YahooPrices


class PeerGroup(BaseModel):
    market: str  # US | IN
    profile: str = "standard"
    members: list[str] = []  # US tickers
    dir: str | None = None  # India: folder of Screener exports


def load_peer_groups(path: str | Path = "config/peers.yaml") -> dict[str, PeerGroup]:
    p = Path(path)
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for name, v in raw.items():
        bad = [m for m in (v or {}).get("members", []) if not isinstance(m, str)]
        if bad:
            raise ValueError(
                f"peers.yaml group '{name}': {bad} is not text. YAML turns bare ON, NO, Y, N into "
                'true/false; put such tickers in quotes, e.g. "ON".'
            )
    return {str(k): PeerGroup(**v) for k, v in raw.items()}


def last_price(prices: YahooPrices, ticker: str) -> float | None:
    try:
        meta = prices.raw(ticker)["chart"]["result"][0]["meta"]
        v = meta.get("regularMarketPrice")
        return float(v) if v else None
    except (KeyError, IndexError, TypeError, ValueError, SourceError):
        return None


class PeerLoader:
    """Loads and caches each group's metrics once per run. Keys are upper-case tickers (US) or
    upper-case company names (India), so a holding can be left out of its own cohort."""

    def __init__(self, groups: dict[str, PeerGroup], cache_dir: str | Path = "data/cache"):
        self.groups = groups
        self.cache_dir = Path(cache_dir)
        self._done: dict[str, dict[str, CompanyMetrics]] = {}
        self.messages: list[str] = []

    def metrics(self, name: str) -> dict[str, CompanyMetrics]:
        if name in self._done:
            return self._done[name]
        g = self.groups.get(name)
        out: dict[str, CompanyMetrics] = {}
        if g is None:
            self.messages.append(f"peer group '{name}' is not defined in peers.yaml")
        elif g.market.upper() == "IN":
            folder = Path(g.dir or "")
            if not g.dir or not folder.exists():
                self.messages.append(f"peer group '{name}': folder {g.dir} not found")
            else:
                for key, c in load_folder(folder).items():
                    out[key] = compute(c, g.profile)
        else:
            edgar, prices = Edgar(self.cache_dir), YahooPrices(self.cache_dir)
            for t in g.members:
                try:
                    c = edgar.company(t, t, last_price(prices, t))
                    out[t.upper()] = compute(c, g.profile)
                except SourceError as exc:
                    self.messages.append(f"peer {t} in '{name}' skipped ({exc})")
        for m in self.messages:
            print(f"  - {m}", file=sys.stderr)
        self.messages = []
        self._done[name] = out
        return out

    def peers_of(self, name: str, exclude: set[str]) -> list[CompanyMetrics]:
        ex = {e.upper() for e in exclude if e}
        return [m for k, m in self.metrics(name).items() if k not in ex]
