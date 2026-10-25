# Parakh v2 backlog

New ideas go here, not into the build. An item enters only if it changes a decision you make with money, at the frequency you make it. Reviewed once, after the M1 review.

## Built since the first version of this list
- Fund look-through exposure across funds and direct holdings (built 24 Oct; live for 5 of 6 funds from 25 Oct)
- Researcher auto-fetch (25 Oct): EDGAR earnings releases and MD&A; Screener-listed India transcripts and results; manual-download list where the exchange refuses; transcript validation. Theses cite real filings; 17 of 19 are MEDIUM confidence
- Perturbation and golden tests against an independent spreadsheet (25 Oct)
- Quarterly drivers: code-owned WATCH drivers from the newest quarter against the same quarter a year earlier (25 Oct)
- ADD gated on confidence and a readable valuation; rupee sizing of trims and adds; acknowledged data-quality flags (24 to 25 Oct)

## Next, in rough order of value
- Sector percentiles and reverse DCF, to replace "P/E against own history" as the valuation anchor
- Per-holding "advice journal" (every label, date and price) to judge the advice after a few quarters
- Supabase `advisory_*` write and the tab contract fixture, then the WealthLens React "Advisory" tab (reads advisory_* via Supabase RLS)
- Scheduled runs (GitHub Actions) and the monthly light check

## Later / maybe
- Show ADD as a first tranche instead of the full gap to the band (IEX: the gap is about 8 times the position)
- Option to ADD only at CHEAP valuation (today ADD also fires at FAIR: ACE, M&M)
- `--refresh-skeptic` to force a new counter-case when the evidence is unchanged but the note is stale
- Indian exchange transcripts without a manual step (needs a permitted source; BSE refuses programs)
- Expense ratio, AUM and manager changes for funds (no free structured source found)
- Tax and exit-load estimate for a Regular-to-Direct switch
- Cost basis for Indian stocks and funds (only if it would change a decision)
- Per-sector concentration cap (the design lists 30%; not enforced yet)
- Inbound MCP / remote access (parked from v1 ADR-012)
