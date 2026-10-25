---
title: Parakh v2 — M1 review agenda
date: 2026-10-25
review: Mon 26 Oct 2026 (90 minutes). Final sign-off: Wed 28 Oct 2026.
status: For the review. Plan of record is 00_SYSTEM_DESIGN_V2.md.
---

# M1 review agenda

**Purpose:** decide whether Parakh v2 is good enough to connect to WealthLens, and settle the choices only you can make. Advisory only; not investment advice.

## 1. Where the build stands (25 Oct)

| | State |
|---|---|
| Positions analysed | 33 positions: 19 stocks with theses (8 US, 11 India), 6 funds, 6 dust positions, gold ETFs and context assets |
| Theses | 17 of 19 at MEDIUM confidence, built on real filings; SHADOWFAX and ATHERENERG stay LOW (short history, losses) |
| Advice today | Trim: AMD, META, AMZN (cap), ELF, TSLA, GOOGL, MAZDOCK. Add: VBL, ACE, IEX, M&M. Review: SHADOWFAX, ATHERENERG. Hold: the rest. Alerts on an identical rerun: 0 |
| Concentration | AMD, META and AMZN are 41.6% of listed equity (cap 35%); three names above the 10% cap |
| Funds | Health cards for 6 funds; stock-level look-through live for 5 (Nippon is exited and leaves with the next CAS) |
| Tests | 129 passing |
| Not built | India peer groups (needs your exports), a live Supabase publish (needs your keys), WealthLens tab |

## 2. How to review (the rubric from the plan)

For each position, in this order of value (AMD, META, AMZN, ELF, TSLA, NVDA, JioBlackRock Flexi Cap, GOOGL, then the rest):

1. Can you say in one sentence why Parakh gives this action?
2. Is every claim in the case file traceable to a source (an evidence ID, a filing, a metric)?
3. Did running twice give the same answer? (Rerun `advise` once; expect 0 alerts.)
4. Is anything stated confidently that the data cannot support?

**Pass:** at least 22 of the 25 advised positions are clean, with no failure on item 4 among the top 8 by value.

## 3. Decisions for you

| # | Decision | Options and my view |
|---|---|---|
| D1 | ADD at FAIR valuation. ACE (+2% against its own median) and M&M (-9%) are ADD at fair | Keep (build toward the band when the thesis is intact) or ADD only at CHEAP. I lean to keep, since the thesis and size already support it |
| D2 | ADD size. IEX's gap to its core band is about 8 times the current position; its P/E is 50% below its median and the Skeptic says the thesis cannot explain why | Show ADD as a first tranche rather than the full gap. I recommend it |
| D3 | Quarterly drivers (built 25 Oct). A weak newest quarter now raises WATCH, which stops adds. Lines: revenue down year on year; profit down over 25%; net margin down over 5 points; three quarters of lower profit | Confirm the lines, or loosen them if one-offs (tax, write-downs) cause too many WATCH flags |
| D10 | Valuation is now the more cautious of own-history P/E and a reverse DCF (US 10%/3%, India 15%/5%, profit as the cash proxy). Lines: 8 points under delivered growth CHEAP, up to +5 FAIR, +5 to +12 RICH, over +12 or any ask above 25% a year STRETCHED | Confirm the rates and lines, or change them. Effect today: AMZN reads FAIR (was CHEAP), SOFI becomes readable (FAIR) |
| D11 | Sector percentiles use named peer groups (starter lists for the 8 US names in `peers.yaml`). Top third lets INTACT read STRONG, which changes no label today | Check the peer lists; export 8 to 12 Indian peers per group if you want India percentiles |
| D12 | Which key writes to Supabase. Service-role keys bypass row security and would give Parakh write access to everything; the design says Parakh never holds the WealthLens service key | Create a key limited to inserting into the `advisory_*` tables (my recommendation), or accept a service key kept out of git |
| D4 | Trims are not gated by confidence (risk is acted on faster) | Keep as designed, or gate. I recommend keep |
| D5 | LAGGING line for funds: 3 points a year behind the benchmark over 3 years (Q10) | Confirm or change |
| D6 | Regular-plan funds (Parag Parikh, SBI Contra, Nippon) cost about 0.8 to 0.9 points a year more than Direct (Q11) | Yours; depends on tax and exit load, which the system does not compute |
| D7 | India transcripts: BSE refuses programs, so about two documents per stock per quarter are saved by hand from the list in `TO_DOWNLOAD.txt` | Accept the manual step, or use the opt-in `--browser-headers` flag, or leave India at filings from Screener only |
| D8 | Per-sector cap of 30% is listed in the design but not enforced | Build, or drop from the design |
| D9 | Tax. Trims are shown before tax; TSLA is up about 2,980% and AMD about 326% | Cost basis is pending for 25 of 33 positions, so the system cannot show tax. Add a cost source only if it would change a decision |

## 4. Limits to state at the review

- Positions are up to 51 days old (CAS of 31 Aug; the next CAS is due next month). Prices are from 21 Oct. Nippon still appears until then.
- The valuation anchor is a stock's own P/E history, a weak anchor. Sector percentiles and reverse DCF are not built.
- There is no evidence yet that this advice adds value. The advice journal and a few quarters will tell.
- Giving advice on named securities to anyone outside your household may fall under SEBI's Investment Adviser rules. Get qualified advice first.

## 5. After the review

| Day | Work |
|---|---|
| Tue 27 Oct | Fixes from the review |
| Wed 28 Oct | Supabase `advisory_*` write and contract fixture; README; final sign-off |
| Later | Scheduled runs (GitHub Actions) and the monthly light check; advice journal; sector percentiles and reverse DCF |

## 6. Before you walk in

- Run `fetch-docs`, `thesis` and `advise` once more so the report is current.
- Open `out/advice.html` and the case files for the top 8 positions.
- Bring the old-repo `v1-final` tag decision (commands are in the plan, §14).
