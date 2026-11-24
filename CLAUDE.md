# CLAUDE.md: parakh-advisor

Guidance for AI coding assistants working in this repo. AGENTS.md points here.

## Project

- Portfolio advisory for a WealthLens portfolio: versioned theses, advice labels, alerts. **Advisory only; never trades.**
- Package `src/parakh_advisor`, Python 3.12, managed with uv. Plan of record: `Stock Analysis\FRAMEWORK\00_SYSTEM_DESIGN_V2.md`; backlog: `FRAMEWORK\BACKLOG.md`.
- Sibling repo `parakh` is the NSE analysis framework. The two are independent; do not import one from the other.
- `.env` holds keys. Never print its values. `data/inbox`, `data/cache`, `data/advice` and `out` are git-ignored personal data.
- `data/theses/**` is tracked and holds your convictions per holding: keep the repo private.

## Rules

- Only `src/parakh_advisor/llm/` may import the Anthropic SDK (ruff `TID251`). Every LLM output is parsed into a typed shape; every loop has a hard cap.
- Time comes from `parakh_advisor.clock` (`now_utc()`, `today_ist()`); never `date.today()` or naive `datetime.now()` (ruff `DTZ`).
- No `print()` outside `cli.py` (ruff `T20`). New code stays under McCabe 15 (ruff `C901`); the `# noqa` markers are the baseline to burn down.
- `contracts/advisory_v1.py` is a frozen shape published to Supabase. A change needs a new version and the frozen-shape test updated on purpose.
- Advice is derived from thesis, valuation and `config/policy.yaml`; thresholds live in YAML, not code.

## Commands (PowerShell)

```powershell
uv sync
uv run pytest
uv run ruff check . ; uv run ruff format .
uv run pyright            # 83 known errors, not in CI yet (backlog)
```
