"""Write an `advisory.v1` bundle to Supabase through its REST interface (PostgREST).

Inserts only, with `ignore-duplicates`, so publishing the same run twice changes nothing and no
existing row is ever updated. `advisory_runs` is written last: a run row means every other row of
that run landed, so the WealthLens tab reads only runs that exist. Needs SUPABASE_URL and a key that
may insert into the advisory_* tables only (see supabase/advisory_v1.sql). Parakh never holds the
WealthLens service key for holdings.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable

from parakh_advisor.contracts.advisory_v1 import CONFLICT, TABLES, Bundle
from parakh_advisor.sources.http import SourceError

Poster = Callable[[str, bytes, dict[str, str]], bytes]
CHUNK = 200


def _post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise SourceError(f"Supabase refused the write (HTTP {exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SourceError(f"Supabase write failed: {exc}") from exc


def publish(
    bundle: Bundle,
    url: str | None = None,
    key: str | None = None,
    post: Poster = _post,
) -> dict[str, int]:
    """Returns rows sent per table. Raises SourceError on the first failure; because runs are
    written last and everything else is idempotent, the safe response to a failure is to re-run."""
    url = (url or os.environ.get("SUPABASE_URL", "")).strip().rstrip("/")
    key = (key or os.environ.get("SUPABASE_KEY", "")).strip()
    if not url or not key:
        raise SourceError("SUPABASE_URL and SUPABASE_KEY must be set in .env to publish")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=ignore-duplicates,return=minimal",
    }
    sent: dict[str, int] = {}
    for table in TABLES:
        rows = bundle.rows(table)
        for i in range(0, len(rows), CHUNK):
            endpoint = f"{url}/rest/v1/{table}?on_conflict={CONFLICT[table]}"
            post(endpoint, json.dumps(rows[i : i + CHUNK]).encode(), headers)
        sent[table] = len(rows)
    return sent
