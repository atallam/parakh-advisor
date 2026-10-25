# Parakh v2 backlog

New ideas go here, not into the build. An item enters only if it changes a decision you make with money, at the frequency you make it. Reviewed once, after the M1 review.

## Built since the first version of this list
- Fund look-through exposure across funds and direct holdings (built 24 Oct; live for 5 of 6 funds from 25 Oct)
- Researcher auto-fetch (25 Oct): EDGAR earnings releases and MD&A; Screener-listed India transcripts and results; manual-download list where the exchange refuses; transcript validation. Theses cite real filings; 17 of 19 are MEDIUM confidence
- Supabase `advisory_*` contract, SQL and writer, with a frozen-shape test (25 Oct, not yet run on a live project)
- Reverse DCF (second valuation reading, the more cautious wins) and sector quality percentiles with US peer groups (25 Oct)
- Perturbation and golden tests against an independent spreadsheet (25 Oct)
- Quarterly drivers: code-owned WATCH drivers from the newest quarter against the same quarter a year earlier (25 Oct)
- ADD gated on confidence and a readable valuation; rupee sizing of trims and adds; acknowledged data-quality flags (24 to 25 Oct)
- Safety net (25 Oct, branch `chore/safety-net-clock-lint`): CI (ruff, format, pytest), pre-commit, CLAUDE.md, one clock (`parakh_advisor.clock`, IST), and lint rules DTZ, T20, BLE, C901 and TID251 with `# noqa` baseline markers

## Next, in rough order of value
- India sector percentiles: **skipped for now (decided 25 Oct)**. Manual Screener exports per peer were judged too inefficient. Revisit only if a structured India fundamentals source appears (an API, or a permitted bulk download)
- Per-holding "advice journal" (every label, date and price) to judge the advice after a few quarters
- Run the SQL in your Supabase project, set keys, first `advise --publish` (needs you); then the WealthLens React "Advisory" tab
- Fill `advisory_evidence` (source, url, excerpt) for the evidence the theses cite
- Scheduled runs (GitHub Actions) and the monthly light check

## Engineering health (from the 25 Oct code review)
Not product scope and not money decisions, so these sit outside the rule above. In order of what each unlocks.

1. **Make `contracts` a leaf.** `contracts/advisory_v1.py` is the frozen shape published to Supabase, yet it imports `advice`, `alerts`, `metrics` and `thesis`, which puts 8 packages in one import cycle. Keep only the models in `contracts/`; move `build_bundle` into `publish/` (or `advice/`). The frozen-shape test stays the gate
2. **Type the LLM client and the `None` comparisons so pyright can join CI.** 83 pyright errors today: 47 in `llm/client.py` (an untyped `dict(...)` of arguments to `messages.create`), 12 in `metrics/quality.py`, the rest in `thesis/rules.py`, `funds/lookthrough.py` and `advice/snapshot.py`. The `None` comparisons may be real bugs when a value is missing
3. **Split the long functions.** `metrics/quality.py: compute` is one 293-line function. Then `cmd_advise` (126 lines), `thesis_analyst.run` (115), `contracts/advisory_v1.py: build_bundle` (124) and `advice/snapshot.py: build_snapshot` (93)
4. **One settings module.** `ANTHROPIC_API_KEY`, `PARAKH_MODEL`, `PARAKH_USER_ID`, `PARAKH_CONTACT`, `SUPABASE_URL`, `SUPABASE_KEY` and `TELEGRAM_*` are read with `os.environ` in 7 places
5. **CLI command registry.** `cli.py` is 443 lines of hand-routed `cmd_*` functions; each area registers its own subcommands, as proposed for `parakh`

### Smaller engineering items
- Burn down the `# noqa: BLE001`, `T201` and `C901` baseline markers; lower `max-complexity` from 15 as they go
- Five `print()` calls in `sources/` library code: use `warnings` or logging
- Privacy: `data/theses/**` (144 tracked files, your convictions per holding) sits in a git repo that carries an MIT LICENSE. Both repos look private today. Before the repo is ever made public, move the theses to a private data repo and drop or rethink the LICENSE
- `data/cache` is about 200 MB inside OneDrive: git-ignored, but synced. Consider a cache folder outside OneDrive
- Windows checkouts show every tracked file as modified (index is LF, working tree CRLF). Add a `.gitattributes` with `* text=auto eol=lf`

## Later / maybe
- Whole-sector US percentiles from EDGAR frames (needs a sector label per filer)
- Reverse DCF on free cash flow instead of profit (needs capex for every company)
- Show ADD as a first tranche instead of the full gap to the band (IEX: the gap is about 8 times the position)
- Option to ADD only at CHEAP valuation (today ADD also fires at FAIR: ACE, M&M)
- `--refresh-skeptic` to force a new counter-case when the evidence is unchanged but the note is stale
- Indian exchange transcripts without a manual step (needs a permitted source; BSE refuses programs)
- Expense ratio, AUM and manager changes for funds (no free structured source found)
- Tax and exit-load estimate for a Regular-to-Direct switch
- Cost basis for Indian stocks and funds (only if it would change a decision)
- Per-sector concentration cap (the design lists 30%; not enforced yet)
- Inbound MCP / remote access (parked from v1 ADR-012)
