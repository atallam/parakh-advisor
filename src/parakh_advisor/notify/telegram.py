"""Plain-text digest of alerts and today's advice, optionally sent through a Telegram bot.

Nothing is sent unless you pass --send to `advise` and TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are set
in .env. Plain text on purpose: no formatting characters to escape, nothing that can break the send.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from parakh_advisor.advice.snapshot import Snapshot
from parakh_advisor.alerts.changes import Alert
from parakh_advisor.sources.http import SourceError

API = "https://api.telegram.org/bot{token}/sendMessage"
LIMIT = 3900  # Telegram's cap is 4096 characters
DOT = {"high": "🔴", "medium": "🟠", "low": "⚪"}

Poster = Callable[[str, bytes], bytes]


def build_digest(snap: Snapshot, alerts: list[Alert], report_hint: str = "") -> str:
    lines = [
        f"Parakh Advisor · {snap.reference_date:%d %b %Y}",
        f"Net worth ₹{snap.net_worth_inr / 1e5:.1f} lakh · advice only, not a trade instruction",
        "",
    ]
    if alerts:
        lines.append(f"ALERTS ({len(alerts)})")
        for a in alerts:
            lines.append(f"{DOT.get(a.severity, '⚪')} {a.symbol}: {a.title}")
            if a.detail:
                lines.append(f"   {a.detail[:200]}")
    else:
        lines.append("No changes since the last run.")
    lines.append("")
    groups: dict[str, list[str]] = {}
    for h in snap.holdings:
        if h.action is not None and h.weight_pct is not None:
            groups.setdefault(h.action.value, []).append(h.symbol or h.name.split(" - ")[0])
    order = ["EXIT", "TRIM", "REVIEW", "ADD", "HOLD", "BUILD OR CONSOLIDATE"]
    lines.append("TODAY'S ADVICE")
    for k in order:
        if k in groups:
            names = groups[k]
            shown = ", ".join(names[:8]) + (f" +{len(names) - 8} more" if len(names) > 8 else "")
            lines.append(f"{k}: {shown}")
    if snap.verdict:
        lines += ["", snap.verdict[0]]
    if report_hint:
        lines += ["", f"Full report: {report_hint}"]
    text = "\n".join(lines)
    return text if len(text) <= LIMIT else text[: LIMIT - 20] + "\n… (truncated)"


def _post(url: str, body: bytes) -> bytes:
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SourceError(f"Telegram send failed: {exc}") from exc


def send(
    text: str, token: str | None = None, chat_id: str | None = None, post: Poster = _post
) -> None:
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise SourceError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env to send")
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    reply = json.loads(post(API.format(token=token), body) or b"{}")
    if not reply.get("ok"):
        raise SourceError(f"Telegram refused the message: {reply.get('description', 'unknown')}")
