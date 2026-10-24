"""Tiny HTTP helper: identifies Parakh to the source, retries with backoff, never swallows errors.

SEC EDGAR requires a descriptive User-Agent with a contact address; mfapi and AMFI do not mind it.
Set PARAKH_CONTACT in .env to your own address.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

Fetcher = Callable[[str], bytes]


class SourceError(RuntimeError):
    """A data source could not be read after retries."""


def user_agent() -> str:
    return f"ParakhAdvisor/0.1 ({os.environ.get('PARAKH_CONTACT', 'personal-use')})"


def http_get(url: str, *, retries: int = 3, timeout: float = 30.0, backoff: float = 1.5) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(backoff**attempt)
    raise SourceError(f"GET {url} failed after {retries} attempts: {last}")


def get_json(url: str, fetch: Fetcher = http_get) -> Any:
    raw = fetch(url)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SourceError(f"{url} did not return JSON: {exc}") from exc
