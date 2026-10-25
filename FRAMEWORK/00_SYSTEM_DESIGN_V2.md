---
title: Parakh v2 — Portfolio Advisory: System Design
version: 2.2 (built and running; filings phase complete, 25 Oct)
date: 2026-10-25
owner: Avinash Tallam
status: LIVE. This is the only plan of record. Everything in archive/v1_universe_engine/ is superseded and read-only.
---

# Parakh v2 — Portfolio Advisory: System Design

> **Advisory only.** Parakh v2 gives a reasoned opinion on the positions you already hold. It never trades, and it is not a licensed investment recommendation. The decision is always yours.

---

## 0. Where the build stands (25 Oct)

Everything in this document marked **built** runs on your PC against your real export (33 positions, 19 stocks with theses, 17 of them at MEDIUM confidence). 129 automated tests pass. Nothing has been connected to WealthLens yet; that is deliberately after testing.

| Piece | State | Notes |
|---|---|---|
| WealthLens JSON ingest, data-quality flags DQ-01..09, risk snapshot, HTML report | **Built** (21 to 23 Oct) | Concentration, dust, staleness, member filter |
| India fundamentals (Screener exports) and US fundamentals (SEC EDGAR) | **Built** | 11 India + 8 US stocks; units kept native (Rs crore / USD million) |
| Quality and valuation metrics | **Built** | Valuation = P/E against own 5-year median (see §7.1) |
| Thesis Analyst, versioned theses, code-owned statuses | **Built** | Anthropic API, `claude-sonnet-5-5`; 19 theses in `data/theses/<SYMBOL>/` |
| Skeptic (bounded tool loop) | **Built** | Writes only the counter-case; cannot change a stance |
| Decision matrix and advice labels | **Built** | §7.3. Conviction is now set for all 19 stocks; ADD needs MEDIUM confidence and a readable valuation |
| Alerts, hysteresis, slow upgrades | **Built and replay-tested** | Identical rerun gives 0 alerts |
| Telegram digest | **Built** | Opt-in with `--send`; not yet sent live |
| Fund health card, category overlap | **Built** (6 funds) | §7.4 |
| Fund stock-level look-through | **Built and live** (5 of 6 funds) | Files read: PPFAS, JioBlackRock, SBI Contra, Invesco, Bandhan. Nippon has no file; it is exited and leaves with the next CAS |
| Researcher: filings auto-fetch (`fetch-docs`) | **Built** (25 Oct) | US fully automatic from SEC EDGAR; India via Screener-listed links, with a manual-download list where the exchange refuses (§8). Theses now cite real filings; 17 of 19 are MEDIUM, SHADOWFAX and ATHERENERG stay LOW |
| Quarterly drivers | Built 25 Oct | Code-owned QM drivers from the newest quarter vs the same quarter a year earlier; WATCH only (§6.3, §13 item 8e) |
| Reverse DCF | Built 25 Oct | Second valuation reading; the more cautious of it and own-history wins (§7.1) |
| Sector percentiles | Built 25 Oct (US live; India skipped by decision) | Peer groups in `config/peers.yaml`; quality percentile can lift INTACT to STRONG (§8) |
| Supabase `advisory_*` write | Built 25 Oct, untested against a live project | Rows, SQL and writer done; needs your Supabase keys (§9.3) |
| WealthLens tab | Not started | After sign-off |

---

## 1. The pivot in one page

| | v1 (archived) | v2 (this document) |
|---|---|---|
| Question it answers | "Which stocks in the market look good?" | "Should I keep, add to, trim or exit what I own, and is the reason I own it still true?" |
| Coverage | Holdings, plus a 500-stock price panel and watchlist ideas | **Only what is in your WealthLens portfolio** |
| Input | CAS PDF parsed by Parakh | **WealthLens holdings** (JSON export now, read-only database view later) |
| Output | Monthly report per stock, Streamlit review app | **A versioned thesis and an advice label per holding**, an HTML report now and a **WealthLens tab** later |
| Key promise | Systematic scoring | **Consistency**: the thesis only changes when evidence changes, and every change raises an alert |
| Size | ~35k lines of Python, 179 acceptance criteria, 19 plan documents | One document, a small repo, finish in 3 to 7 days |

**What is retired:** universe screening, the benchmark price panel as a product, the watchlist and curator, momentum calibration, the orchestrator and MCP server, the Streamlit app, AWS SSM secrets, the 34-item Production gate and the 179 acceptance criteria.

**What carries over as principles:** numbers come from code and the LLM never invents a number (the v1 "numbers firewall"); evidence first, with every claim traceable to a source; honest "limited history" and "unknown" states; an LLM may flag a broken thesis but only a measurable rule or you can confirm it; ISIN as the identity key; Telegram as the alert channel.

---

## 2. What your portfolio export tells us (this drives the design)

Source: the WealthLens `holdings` export of 21 Oct 2026, 57 active rows, USD/INR 94.995.

| Asset class | Value (₹ lakh) | % of net worth | Advisory treatment |
|---|---|---|---|
| US stocks (8) | 92.25 | 38.4% | Thesis + action |
| Fixed deposits (16) | 75.61 | 31.5% | Context only |
| Mutual funds and gold ETF (8) | 23.04 | 9.6% | Fund health card + overlap |
| PPF (2) | 21.45 | 8.9% | Context only |
| Insurance (4) | 16.54 | 6.9% | Context only |
| Indian direct stocks (17) | 7.11 | 3.0% | Thesis + action |
| EPF, cash | 4.12 | 1.7% | Context only |
| **Total** | **240.12** | | |

Within **listed equity** (US + India direct + funds = ₹122.4 lakh): **US stocks are 75%, funds 19%, Indian direct stocks 6%.**

Findings that change the plan:

1. **The v1 pilot covered about 6% of your listed equity.** The biggest risks and decisions are in eight US names. AMD (16.6%), META (14.6%) and AMZN (10.2%) alone are 41% of listed equity. **US stocks must be in scope.** This reverses the 11 Oct "consider later" decision, and the reason is the data above.
2. **Concentration is a larger and more certain finding than any thesis.** The first useful output is the risk view, so it ships first.
3. **Six Indian holdings are too small to matter** (₹2k to ₹7k each, ₹0.30 lakh in total): SHYAMMETL, TMPV, PPLPHARMA, SBICARD, TMCV, KIMS. "Trim" is meaningless for them. The advice is "build up or consolidate".
4. **Cost basis exists only for the 8 US stocks.** All 17 Indian stocks and all 8 funds show `purchase_price = 0` and `avg_cost = null`. You decided to leave these as "cost pending" for now (Q2), so P&L is blank for those rows.
5. **Positions are stale.** CAS rows are as of 31 Aug (51 days old) and SnapTrade rows as of 1 Oct (20 days). Prices are fresh (21 Oct). Every output carries a "positions as of" banner.
6. **Fund names are ambiguous.** "INVESCO MUTUAL FUND", "BANDHAN MUTUAL FUND", "HDFC MUTUAL FUND" and "JIO BLACKROCK MUTUAL FUND" do not name the scheme. They resolve by ISIN against the AMFI NAV file.
7. **Identity is messy.** Tickers mix `.NS` and `.BO` (MAZDOCK, TMPV), names carry `#NEW`, and TMPV and TMCV appear to be the two post-demerger Tata Motors entities. The gold ETF is typed `MF`. `asset_class` is null on every row. SnapTrade `start_date` is the sync date, not a purchase date. Four `member_id` values mean a family-level portfolio.
8. **One cost basis looks suspect.** TSLA shows $12.13 against $373.71 (30.8×). It may be split-adjusted legacy cost. It is flagged for you to verify, not corrected silently.

---

## 3. Principles

1. **Advice, not action.** Output says what and why. It never places orders. Every screen carries the advisory notice.
2. **Consistency over cleverness.** A thesis is a versioned object. Later runs test it, they do not rewrite it from scratch.
3. **Separate the three questions.** *Is it a good business?* (thesis stance) · *Is the price reasonable?* (valuation stance) · *Is the position the right size for me?* (policy fit). The action label is derived from these three by a visible rule, not by LLM judgement.
4. **Numbers from code, words from the LLM.** The LLM proposes drivers, thresholds and narrative. Code computes every metric and every status.
5. **Original, evidence-first thesis.** Built from filings, financials and call material. **Analyst ratings and price targets are not inputs**, so the view is not anchored to consensus. No price targets or ratings of our own either.
6. **Honest unknowns.** Thin history, missing data or low confidence produce "insufficient evidence", never a confident guess.
7. **Quiet by default.** No message means nothing changed.
8. **Built to be absorbed by WealthLens.** Same stack where it matters, a data contract in place of a UI, and the report layout is the future tab layout.

---

## 4. Scope

**In**
- Direct equities, India and US (25 positions today)
- Mutual funds and ETFs: a fund health card and overlap warning, not a stock-style thesis
- Portfolio risk: concentration, sector and country mix, position sizing, dust
- Thesis versioning, change detection and alerts

**Context only** (counted in totals, no advice): FD, PPF, EPF, insurance, cash.

**Out**
- Watchlists, discovery and screening of stocks you do not own
- Tax (your decision). Every output is pre-tax, with one standing line: "check tax impact before acting on large trims"
- Trading, brokerage connections, intraday signals
- Own earnings forecasts, price targets and ratings
- Crypto and US bonds (no holdings today)

---

## 5. How the system works

```
WealthLens holdings (JSON now, DB view later)
        │  contract holdings.v2
        ▼
 ┌─────────────┐    ┌──────────────────────┐
 │ Ingest +    │───▶│ Position facts       │  weight, cost basis, P&L,
 │ normalise + │    │ (code)               │  concentration, dust, staleness
 │ data-quality│    └──────────┬───────────┘
 └─────────────┘               │
        ┌──────────────────────┴──────────────────────┐
        ▼                                             ▼
 Multi-source evidence                         Peer / sector context
 (filings, financials, calls, prices)          (percentiles, closest peers)
        │                                             │
        └───────────────┬─────────────────────────────┘
                        ▼
          Metrics and driver status (code)
                        │
        ┌───────────────┴────────────────┐
        ▼                                ▼
 Thesis Analyst (LLM, structured)   Skeptic (LLM agent loop, bounded)
        └───────────────┬────────────────┘
                        ▼
        Thesis version  +  change decision: REAFFIRM / AMEND / REPLACE
                        │  (hysteresis and burden of proof, code)
                        ▼
      Stance (code) × Valuation (code) × Policy fit (code)
                        ▼
              Action label + reason codes
                        ▼
   advisory.v1 tables ──▶ HTML report · Telegram alerts · WealthLens tab
```

### 5.1 Components

| Component | Responsibility | LLM? |
|---|---|---|
| Ingest | Read the holdings export, normalise identities, run data-quality checks | No |
| Sources | Fetch evidence behind one interface with fallbacks and provenance (§8) | No |
| Metrics | Quality scorecard, valuation vs history and sector, trend; driver statuses | No |
| Researcher | Reads filings and call material, extracts cited facts into the evidence store | Yes, single-shot, structured |
| Thesis Analyst | Drafts a new thesis, or tests the prior one against new evidence | Yes, structured |
| Skeptic | Looks for disconfirming evidence and writes the counter-case | Yes, **a real agent loop** with tools and a hard iteration cap |
| Judge | Derives stance, applies hysteresis, computes the action label, raises alerts | No |
| Reporter | Renders HTML, Telegram digest, and writes `advisory_*` tables | No |

The agentic part is deliberately small: one genuine tool-using agent (the Skeptic) plus structured single-shot calls. That is enough to learn agent behaviour on real data without turning a one-week project into an orchestration project. Each role sits behind an interface, so any of them can become a fuller agent later.

---

## 6. Thesis consistency: the core of the product

### 6.1 The thesis is a versioned object

```yaml
thesis:
  instrument_id: "INE646L01027"       # ISIN, or "US:NVDA" when no ISIN
  version: 3                          # immutable once written
  as_of_data_date: 2026-10-20
  model: "<model id>"
  prompt_version: "thesis_analyst@1.2"
  inputs_digest: "sha256:..."         # hash of the evidence set used
  business_summary: "<=60 words"
  why_own: "<=2 sentences: the core claim"
  drivers:                            # 3 to 5, fixed when the thesis is created
    - id: D1
      statement: "..."
      kind: metric | qualitative
      indicator: "MET.revenue_growth_yoy"      # metric drivers only
      warn_threshold: ...
      break_threshold: ...
      status: OK | WATCH | BROKEN | UNKNOWN    # computed, not opined
      evidence_ids: [E12, E31]
  kill_criteria:                      # 1 to 3, measurable, pre-registered
    - id: K1
      rule: "MET.net_debt_ebitda > 4 for 2 consecutive quarters"
      tripped: false
  valuation:
    method: "reverse_dcf | multiple_vs_history | multiple_vs_sector"
    implied_expectation: "..."
    sector_percentile: 72
    stance: CHEAP | FAIR | RICH | STRETCHED | NA
  risks: [ ... at least 2, each with evidence_ids ]
  stance: STRONG | INTACT | WEAKENING | BROKEN | INSUFFICIENT   # derived, §6.3
  confidence: HIGH | MEDIUM | LOW                                # derived from data coverage and history
  skeptic_counter_case: "..."
  change_decision: NEW | REAFFIRM | AMEND | REPLACE
  change_log: [ {field, from, to, new_evidence_ids} ]
```

### 6.2 Rules that keep it consistent

1. **Pre-registration.** Drivers, thresholds and kill criteria are written when the thesis is created. Later runs *evaluate* them. They do not re-argue the story.
2. **Burden of proof on change.** A new run receives the prior thesis and must return REAFFIRM (default), AMEND (named fields change) or REPLACE. Any change must cite evidence **dated after the prior version**. A change with no new evidence is rejected by code and logged.
3. **Statuses are computed.** Metric drivers are scored by code against thresholds. Qualitative drivers may be moved to WATCH by the LLM with a quoted source. **Only a tripped kill criterion or your confirmation makes a driver or the thesis BROKEN** (carried from v1).
4. **Asymmetric hysteresis.** A downgrade needs one confirmed new filing or a tripped kill criterion. An upgrade needs two consecutive evaluations at the higher level. Risk is acted on faster than optimism.
5. **Deterministic replay.** Temperature 0, evidence cached by content hash. Re-running on the same inputs must reproduce the same stance and action. This is a test (§12).
6. **Everything versioned.** Prompts, models, policy and evidence sets are versioned, so a changed answer can be traced to a changed input.

### 6.3 Deriving the stance (code)

| Condition | Stance |
|---|---|
| Any kill criterion tripped, or you confirmed BROKEN | **BROKEN** |
| Any driver BROKEN or WATCH | **WEAKENING** (changed 23 Oct: one driver already past its warn line is not "intact") |
| All drivers OK or UNKNOWN with at least half measurable and OK | **INTACT** (confidence LOW when the thesis has no filing or quoted source) |
| INTACT and quality scorecard in the top third of its sector, with no WATCH | **STRONG** |
| Fewer than 2 measurable drivers, or fewer than 8 quarters of reported history | **INSUFFICIENT** (confidence LOW) |

**Added after the first real runs (23 to 24 Oct):**

- **Loss-making with no earnings record** (negative trailing profit and fewer than 2 profitable years) is INSUFFICIENT, not INTACT (Ather came out INTACT while losing money).
- **Code-added hygiene drivers.** When a thesis is created, code (not the model) adds warn-only drivers for the red flags the model chose inconsistently from run to run: cash conversion below 0.5x profit (skipped for brokers, where client money distorts it), interest cover below 1.5x (skipped for banks), negative trailing profit, trailing P/E more than 30% above its own history, return on equity below 10%, and trailing P/E above 60x. They can raise WATCH and never BROKEN, so they can make a stance WEAKENING but cannot trip an exit.
- **Warn lines are pulled in.** The Skeptic kept saying the model's thresholds were lenient (a margin driver that only warns after most of the gain is gone). At creation, any warn line more than 30% away from today's value is moved to 30% and the break line kept beyond it; the driver text records the change.
- **Qualitative drivers** can be set to WATCH only with a quote that appears verbatim in a cited document. BROKEN and OK from the model are refused.
- **Retries.** Occasionally the model's JSON is rejected by the schema (a different company each run). `thesis` retries up to 3 times and lists any that still fail.
- Confidence is LOW for any thesis with no filing or quoted source. Since 25 Oct a filing counts only if it is dated within 400 days of the newest evidence, so an old filing cannot lift a thesis to MEDIUM. With `fetch-docs` and your saved transcripts, 17 of the 19 theses are MEDIUM; SHADOWFAX and ATHERENERG remain LOW (INSUFFICIENT) because of short history and losses.
- **Model output handling (25 Oct).** Thesis replies are allowed 8,000 tokens (3,000 cut off long AMEND replies mid-sentence), a cut-off reply is reported as such, and the JSON reader takes the first complete object and ignores stray text after it.

Young listings (GROWW, SHADOWFAX, ATHERENERG, SAGILITY, TMPV, TMCV) will usually land on INSUFFICIENT or LOW confidence at first, and the report says so. This replaces v1's "limited-history" machinery with one rule.

### 6.4 Alerts

| Severity | Trigger | Channel |
|---|---|---|
| **High** | Stance moves to BROKEN; kill criterion tripped; position above cap by more than 5 points; action becomes EXIT | Telegram immediately + report banner |
| **Medium** | Stance downgrade; driver status flip to WATCH or BROKEN; action label changes | Telegram + report |
| **Low** | Stance upgrade; data staleness; new thesis created | Weekly digest |

**As built:** upgrades must be seen on two consecutive runs (downgrades are immediate). "Position far above the cap" fires once, when it first crosses 5 points, not every run. The first run produces one baseline summary instead of one alert per thesis. State lives in `data/advice/state.json`. Replay-tested: an identical rerun gives zero alerts. Every `advise` run writes `out/digest.txt`; `--send` posts it to Telegram (token and chat id in `.env`).

Alert text always includes: what changed, the evidence ID(s), the previous and new value, and "what would reverse this".

### 6.5 Cadence

| Run | When | LLM use |
|---|---|---|
| **Full refresh** | Within 7 days after a holding files results (India results, US 10-Q/10-K or 8-K Item 2.02) | Yes |
| **Light check** | Monthly | No, unless something trips |
| **Event trigger** | Kill-criterion metric trips; one-day move beyond 3σ; material 8-K items or exchange announcements (auditor change, pledge, rating action, M&A); a new buy or sell appears in WealthLens | Yes, for the affected holding only |

---

## 7. From thesis to advice

### 7.1 Three inputs, one label

- **Thesis stance** (§6.3)
- **Valuation stance**: CHEAP / FAIR / RICH / STRETCHED / NA. There are no price targets. **Version 1, as built:** today's P/E against the median of the stock's own last five fiscal-year-end P/Es (under -20% CHEAP, up to +20% FAIR, up to +40% RICH, above that STRETCHED). Two guards: if trailing profit is more than 1.4x last fiscal year's (often one-off gains, as at GOOGL, AMZN, NVDA), the fiscal-year P/E is used so a one-off cannot make a stock look cheap; and the result is NA when history is too short, profit is negative, or the history is distorted (HDFC Bank after the 2023 merger). US history uses fiscal-year-end prices from Yahoo with split effects undone, divided by EPS from as-first-reported share counts. **Version 2 (25 Oct), the label is the more cautious of two readings.** Reading 1 is the own-history P/E above. Reading 2 is a reverse DCF: the yearly profit growth that today's market value asks for over ten years, followed by a terminal rate (US 10% discount and 3% terminal; India 15% and 5%; profit stands in for free cash flow), compared with the growth the company has delivered (3-year profit CAGR, else revenue; past growth above 25% is capped). Gap of 8 or more points below delivered growth is CHEAP; -8 to +5 FAIR; +5 to +12 RICH; +12 or more STRETCHED; any ask above 25% a year is STRETCHED whatever the history. The profit base is the lower of last fiscal year and trailing four quarters. Where own-history is unreadable the reverse DCF alone gives the label; where history is flagged unreliable (HDFC Bank) only the absolute ask counts, since past growth is distorted too. NA only when both are unreadable. The thresholds are blunt heuristics, not forecasts.
- **Policy fit**: position weight against your bands (below). Policy is yours, in `policy.yaml`.

### 7.2 Policy defaults (yours to change)

| Parameter | Default |
|---|---|
| Position bands by conviction | Core 6–10% · Standard 3–6% · Starter 1–3% · Tracking under 1%. **Conviction is unset until you set it** in `config/instruments.yaml`; unset means only the concentration cap applies (changed 24 Oct, after every holding defaulted to Tracking and GOOGL was trimmed for being over 1%). Only Core and Standard can ever produce ADD |
| Single-name cap | 10% of listed equity |
| Top-3 cap | 35% |
| Single-sector cap | 30% |
| Dust threshold | Under 0.1% of listed equity (about ₹12k today). *Corrected 21 Oct from 0.5%, which would have flagged 9 Indian stocks instead of the 6 tiny ones* |
| Hysteresis buffer | Leave TRIM only when 2 points under the cap |
| Discount rates for reverse DCF | **US 10%** (decided 21 Oct). India 15% carried from v1 until you say otherwise |

These are defaults, not wisdom. They are the part of the system you must own.

### 7.3 Decision matrix

| Thesis | Valuation | Weight vs band | Action |
|---|---|---|---|
| STRONG / INTACT | CHEAP / FAIR | Below target | **ADD** (only if conviction tier is Core or Standard) |
| STRONG / INTACT | any | Within band | **HOLD** |
| INTACT | RICH / STRETCHED | Above target | **TRIM** toward target |
| any | any | Above cap | **TRIM** to cap (reason code: concentration, regardless of thesis) |
| WEAKENING | any | any | **HOLD, no adds**, review date set; with RICH or STRETCHED: **TRIM** |
| BROKEN | any | any | **EXIT** (consider), needs your confirmation to stay BROKEN |
| INSUFFICIENT | any | any | **REVIEW** (the system will not pretend to know) |
| any | any | Dust | **BUILD OR CONSOLIDATE**: too small to matter |

**ADD gating (25 Oct).** ADD needs thesis confidence of MEDIUM or higher and a readable CHEAP or FAIR valuation. With LOW confidence the label is REVIEW, and below the band with no readable valuation (too little history, losses, or distorted earnings) it is HOLD with the reason "will not suggest adding". Trims are not gated by confidence, so risk is acted on faster than optimism.

Every label carries **reason codes** and **"what would change this advice"**. A concentration TRIM and a thesis TRIM are shown as different reasons, because acting on them differs.

### 7.4 Mutual funds and ETFs

A fund health card, not a thesis. **Built (24 Oct)**, from AMFI NAV history through mfapi.in (cached one day):

- 1, 3 and 5-year returns against a benchmark proxy: a Direct-plan index fund (Nifty Smallcap 250 for small-cap funds, Nifty 500 for everything else). There is no free index feed; index funds track closely, less a small cost.
- How often the fund beat the benchmark over rolling one-year windows in the last 3 years; volatility and worst fall.
- For Regular plans: the measured return gap to the same scheme's Direct plan over 3 years (found by name search), not an assumed expense ratio.
- **Verdict by rule:** HEALTHY (ahead over 3 years and winning at least half the windows), WATCH (behind by less than 3 points a year), LAGGING (3 or more points behind; advice REVIEW), TOO_NEW (under 3 years), NO_DATA. Labels are HOLD or REVIEW; the report suggests checking a Regular-to-Direct switch but never tells you to, because tax and exit load decide it.
- **Category overlap:** categories held through two or more funds (your 2 flexi caps are 9.8% of listed equity; 3 small caps 7.5%).
- **Stock-level look-through (built, needs files):** each fund's monthly portfolio file from the fund house site, dropped in `data/inbox/funds/`, is read to show, per direct stock, the share held directly and through funds; true US exposure including funds; and fund pairs holding the same companies. PPFAS's US holdings are measured from its disclosure, not assumed.
- Not built: expense ratio, AUM and manager changes (no free structured source).

---

## 8. Data sources (multi-source by design)

Every field is fetched through a `Source` interface that returns the value with **provenance** (source, retrieved_at, URL or hash). Each field has a primary, a cross-check and a fallback. A disagreement above a tolerance raises a data-quality flag instead of silently picking one.

| Data | India | US | Funds |
|---|---|---|---|
| Positions, cost | WealthLens (+ cost source, Q2) | WealthLens (SnapTrade) | WealthLens (CAS) |
| Fundamentals | **Screener.in export** (manual, primary; XBRL cross-check) | **SEC EDGAR** company facts (primary); yfinance fallback | AMFI scheme data |
| Prices and history | Exchange archives / yfinance | yfinance (unofficial; fallback to be chosen) | **AMFI NAV** (official), mfapi.in as backup |
| Call and results material | Screener company page lists the BSE-filed transcripts and results; documents downloaded by `fetch-docs`, or saved by you when BSE refuses | 8-K Item 2.02 EX-99.1 releases (last 3) and the 10-Q/10-K MD&A, fully automatic | n/a |
| Events | Exchange announcements | EDGAR 8-K | AMC notices |
| FX | WealthLens `usd_inr_rate` for valuation; RBI or yfinance history | | |
| Sector valuation | **NSE sector-index P/E, P/B, yield** (v1 fixtures exist) | EDGAR-derived | n/a |

**Status of each source (spiked 23 Oct, from the build container):**

| Source | Result | Decision |
|---|---|---|
| SEC EDGAR company facts, frames, ticker map | Works; requires a descriptive User-Agent (set `PARAKH_CONTACT`) | Primary for US fundamentals |
| mfapi.in (AMFI mirror) | Works; scheme name, SEBI category, fund house, full NAV history, name search | Resolves funds and supplies NAV history for the health card; cached on disk |
| AMFI NAVAll | Works only when following the redirect to portal.amfiindia.com | Backup for NAV history |
| Yahoo chart endpoint | Works for prices and splits; rate-limits bursts (HTTP 429); `quoteSummary` needs a crumb and returns 401 | Used for US fiscal-year-end prices and splits, with pauses, retries and a cache; no fundamentals from Yahoo |
| Stooq | Blocked from the container | Dropped |
| Screener.in export (Data Sheet v2.1) | Parsed deterministically; all 11 of your exports load | Primary for India fundamentals |

| Screener company page (documents list) | Works; one page per company, cached one day, 1 second pause | Source of transcript and results links for India |
| BSE document links (`AnnPdfOpen.aspx`) | **HTTP 403 to programs**, from the cloud and from your home connection | Not worked around. Refused documents are listed in `TO_DOWNLOAD.txt` per stock; you save the PDF from your browser. `fetch-docs --browser-headers` is an opt-in you switch on yourself |
| concall.in | Pages are an empty JavaScript shell behind a login; `/api/` is disallowed by robots.txt | Not used (it was optional in v1 too) |
| EDGAR filing index page | Works; labels each document's type (EX-99.1) | Used to find the earnings release, because file names differ by company (AMD's is `q22026991.htm`) |

**Used in production runs (24 Oct):** EDGAR for the 8 US stocks (needs your real email in `PARAKH_CONTACT`; SEC rejects anonymous requests); Screener exports for the 11 Indian stocks; mfapi.in for funds; Yahoo chart for US prices. Operating leases are excluded from US debt; US quarters are the three-month 10-Q figures with Q4 derived.

**Found by the spike:** the WealthLens row for HDFC "MUTUAL FUND" (INF179KC1981) is the HDFC Gold ETF. Fund names from WealthLens are unreliable, so every fund is now resolved by scheme code and reclassified (gold ETFs move to the commodity sleeve, outside listed equity).

### Sector context: your "don't limit to 4–5 peers" answer

I agree, with one adjustment based on what data is actually obtainable.

- **US:** use the whole sector. EDGAR's bulk "frames" data returns one metric for every filer in a period, so percentile ranks for growth, margins, returns on capital and leverage across the full sector are cheap. **As built (25 Oct) this changed:** frames carry no sector label (that needs a lookup per company), so US uses the same named peer groups as India, 9 to 13 tickers each in `config/peers.yaml`, run through the identical metric code. Whole-sector frames stay a later option.
- **India:** there is no free bulk source for fundamentals, and Screener exports are manual and one stock at a time. Whole-sector fundamentals are therefore **not feasible in a week**. Instead: sector *valuation* comes from NSE index P/E, P/B and yield (already proven), and operating-metric comparison uses a **closest-peers cohort** of about 8 to 12 names that you export from Screener once per quarter.
- **Both:** the Skeptic gets the peer table so the counter-case is grounded.
- Sector labels are noisy (Tesla as "autos", Amazon as "retail"). Percentiles are shown with the cohort size and the sector definition used.

**As built.** `config/peers.yaml` defines groups; a holding joins one with `peer_group:` in `instruments.yaml`. Quality percentile = average rank of 3-year revenue growth, ROCE, operating margin, debt/equity (lower is better) and cash conversion; banks use revenue growth, profit growth and ROE. Fewer than 5 usable peers or fewer than 3 rankable measures gives no percentile and says why. A score of 66.7 or more (top third) lets an INTACT thesis read STRONG. A P/E percentile is shown as information only. The holding is never in its own cohort. India holdings carry no percentile: there is no free structured fundamentals source for Indian peers and manual Screener exports per peer were judged too inefficient (decided 25 Oct). The loader still supports a folder of exports (`market: IN, dir:`) if that ever changes.

---

## 9. Integration with WealthLens

### 9.1 Stack alignment

| Layer | WealthLens today | Parakh v2 | Why it fits |
|---|---|---|---|
| Database and auth | Supabase (Postgres, Auth, RLS) | **Same Supabase**; new `advisory_*` tables | No new infrastructure, one login |
| Compute | Node/Express on Render | **Python 3.12 batch job** (CLI, then scheduled) | Python is your preference and the right tool for analysis |
| UI | React 18 + Vite | HTML report now; **React tab later reads `advisory_*` through Supabase with RLS** | No Python in the request path |
| Boundary | | **Two versioned contracts** (§9.2, §9.3) | WealthLens owns holdings, Parakh owns analysis. Neither reaches into the other's tables |

### 9.2 Input contract `holdings.v2` (from WealthLens)

Used fields and how each is normalised:

| WealthLens field | Use in Parakh |
|---|---|
| `isin` (else `ticker`) | `instrument_id`. India and funds use the ISIN. US uses `US:<ticker>` until a CUSIP or CIK mapping is added |
| `type` | Asset-class map: `IN_STOCK`, `US_STOCK` → equity · `MF` → fund (gold-ETF name pattern reclassified) · `FD`, `PPF`, `EPF`, `INSURANCE`, `CASH` → context |
| `name` | Display name, cleaned (`#NEW`, trailing `-` and `#` removed) |
| `units`, `current_price`, `currency`, `usd_inr_rate` | Market value in INR = units × price × FX |
| `avg_cost`, else `purchase_price` / `purchase_nav` | Cost per unit. A value of `0` or null means **cost pending**, never zero |
| `source`, `source_date`, `cas_period_end`, `last_synced`, `price_fetched_at` | Position and price "as of" dates, staleness flags, source confidence |
| `scheme_code`, `isin` (funds) | Resolve the real scheme name through AMFI |
| `member_id` | Owner. Default scope: all members combined, with a member filter (Q3) |
| `holding_status` | Only `active` rows are analysed |
| `brokerage_name`, `depository` | Account label |
| `start_date` | **Ignored as a holding period** for SnapTrade rows (it is the sync date) |
| everything else (`interest_rate`, `maturity_*`, `policy_type`, `premium_*`, …) | Passed through for context assets only |

**Data-quality rules (each produces a visible flag, not a silent fix):**

- DQ-01 cost missing or zero · DQ-02 position older than 30 days · DQ-03 price older than 3 days · DQ-04 cost-to-price ratio above 10× or below 0.1× (TSLA today) · DQ-05 ticker or listing mismatch (`.BO` vs `.NS`) · DQ-06 fund scheme unresolved · DQ-07 two instruments sharing a corporate lineage (TMPV/TMCV) · DQ-08 asset class null or inconsistent.

**Transport:** Milestone 1 reads the JSON export. Phase 2 reads a **read-only Supabase view** (`v_parakh_holdings`) with a scoped role. Parakh never holds the WealthLens service key.

### 9.3 Output contract `advisory.v1` (to WealthLens)

```sql
advisory_runs       (id, user_id, kind, started_at, finished_at, model, policy_version, status)
advisory_theses     (id, user_id, instrument_id, version, created_at, stance, confidence,
                     valuation_stance, change_decision, body jsonb, inputs_digest)   -- immutable rows
advisory_drivers    (thesis_id, driver_id, kind, indicator, status, value, evidence_ids)
advisory_actions    (id, user_id, instrument_id, run_id, action, reason_codes text[],
                     weight_pct, band_low, band_high, what_would_change text, created_at)
advisory_alerts     (id, user_id, instrument_id, severity, kind, prev_value, new_value,
                     evidence_ids text[], created_at, acknowledged_at)
advisory_evidence   (id, user_id, instrument_id, source, url, retrieved_at, content_hash,
                     excerpt, quality_tier)
advisory_portfolio  (run_id, user_id, snapshot jsonb)   -- allocation, concentration, dust, DQ flags
```

**As built (25 Oct):** `contracts/advisory_v1.py` builds the rows, `supabase/advisory_v1.sql` creates the tables, policies and two current-state views, and `publish/supabase.py` writes them (`advise --publish`). Ids are content-derived so re-publishing is a no-op; `advisory_runs` is written last as the completion marker. `advisory_evidence` is defined but not yet filled. A frozen-shape test fails on any column change until the version is bumped.

Rules: every table carries `user_id` with an RLS policy; rows are append-only (current state is a view over the latest version); the contract is versioned (`advisory.v1`) so the React tab never breaks on a Python change.

### 9.4 The future WealthLens "Advisory" tab

The HTML report built in this project **is the tab's design prototype**, section for section, so the port is mechanical.

1. **Header verdict**: three lines in plain language ("Concentration is the main issue: 3 US names are 41% of equity", "2 theses weakened since last run", "6 positions too small to matter").
2. **Data health banner**: positions as of, cost-basis gaps, unresolved funds.
3. **Positions table**: action chip, thesis stance, valuation chip, weight vs band bar, one-line reason, sortable by "needs attention".
4. **Case file** (click through): thesis card; driver status lights; kill criteria; "what changed since the last version"; the Skeptic's counter-case; evidence list with sources; "what would change this advice".
5. **Alerts feed**, with acknowledge.
6. **Portfolio view**: allocation, sector and country mix, concentration, overlap.

UX rules: answer first, details on demand; one screen per decision; honest empty and unknown states; readable on a phone; no jargon without a tooltip.

---

## 10. Repository and engineering

**Decision: new repo, old repo frozen.** The v1 repo has CI gates tied to the v1 plan (acceptance-criteria traceability, doc lint, layering lint, the 34-item checklist). Deleting 70% of the code would fail those gates repeatedly, so rewriting in place costs more than starting clean.

- Old: `Stock Analysis\parakh` stays as-is. Tag `v1-final` and add a "superseded" note to its README (PowerShell in §14).
- New: `Stock Analysis\parakh-advisor`, GitHub `atallam/parakh-advisor` (private).
- Tier: **Proto plus selected Production items** (Q5). Kept: secrets handling, Pydantic validation, retry with backoff, hard iteration caps, structured logs, prompts in versioned files, mocked LLM in CI, golden tests. Dropped for now: the full 34-item gate.

```
parakh-advisor/                     (as built, 25 Oct)
  config/        policy.yaml · instruments.yaml        (instruments: ISIN/ticker -> source names, sector, profile, conviction)
  data/          inbox/ (holdings.json · screener/ · funds/) · theses/<SYMBOL>/vNNNN.json · advice/state.json · cache/
  research/      documents you supply per symbol (optional)
  src/parakh_advisor/
    contracts/   holdings_v2.py                         (Pydantic)
    ingest/      wealthlens_json.py · normalise.py · dq.py · instruments.py
    sources/     http.py · companies.py · india/screener_export.py · us/edgar.py · us/filings.py · us/prices.py · india/screener_docs.py · india/transcripts.py · text.py · funds/mfapi.py
    metrics/     quality.py
    thesis/      models.py · evidence.py · rules.py · store.py
    llm/         client.py (Anthropic, retry, FakeLLM for tests)
    agents/      thesis_analyst.py · skeptic.py        (+ prompts/*_v1.md)
    research/    documents.py · fetch.py
    advice/      snapshot.py · valuation.py · matrix.py · apply.py · funds.py · policy.py
    funds/       health.py · lookthrough.py
    alerts/      changes.py
    notify/      telegram.py
    report/      html.py · templates/portfolio.html.j2
    cli.py       snapshot · metrics · thesis · advise · fetch-docs
  tests/         129 tests (contract, DQ, metrics, thesis, matrix, replay, funds, EDGAR, filings fetch)
  CHANGELOG.md   every change, newest first
```

**What to port from v1** (candidates only; each is read and tested before reuse):

| v1 module | Lines | Decision |
|---|---|---|
| adapters (Screener export, prices, XBRL, corporate actions) | 2,364 | **Port** the Screener parser and price/XBRL adapters; drop CAS |
| notify (Telegram) | 2,223 | **Port** the Telegram sender only |
| thesis, lenses (value profiles) | 700 + 699 | **Mine for ideas** (status model, sector profiles for airlines, SOTP and similar) |
| quality, observability, llm, privacy | ~1,200 | **Port** the useful parts |
| analytics | 4,084 | **Selective port** of metric functions |
| services, orchestration, calibration, mcp, watchlist, watch, governance, policy, snapshots, registry, configs, render, storage | ~16,000 | **Cut** (rewrite render and storage for v2) |
| agents | 1,229 | **Rewrite** as three roles; reuse runtime ideas |

Expect to reuse roughly 15 to 20% of v1 code. The larger inheritance is the lessons, not the lines.

---

## 11. Delivery plan: 7 days, with a 3-day and 5-day cut

Calendar: today is Wed 21 Oct 2026 (Day 0). Your time is review, not typing: about 20 to 30 minutes a day plus one 90-minute review on Day 5.

| Day | Date | Build | You |
|---|---|---|---|
| **0** | Wed 21 Oct | Sign-off on this document; archive v1 (done); create the repo skeleton | Answer Q5, Q6 and the US discount rate |
| **1** | Thu 22 Oct | Contracts, WealthLens JSON ingest, normalisation, DQ report, **portfolio snapshot**: allocation, concentration, dust, staleness. First HTML page | Check the DQ flags (cost, TSLA). **Built early on 21 Oct: 34 tests pass, report renders on desktop and phone** |
| **2** | Fri 23 Oct | Source spikes (EDGAR, AMFI, US prices), India price and Screener loaders, FX, fund scheme resolution. Metrics and sector percentiles | Export Screener files for the Indian holdings and peers |
| **3** | Sat 24 Oct | Thesis schema, LLM client, Researcher and Thesis Analyst. First theses for the US names and the 11 sizeable Indian names | Skim the first theses for sense |
| **4** | Sun 25 Oct | Skeptic agent loop, stance derivation, hysteresis and diff, action matrix, alerts. Run all 25 positions | |
| **5** | Mon 26 Oct | HTML report v1, Telegram digest, fund health cards. **M1 review (90 min)** | Review against the rubric below |
| **6** | Tue 27 Oct | Fixes from review; consistency tests (replay, perturbation); golden theses | Re-check changed items |
| **7** | Wed 28 Oct | `advisory_*` tables and Supabase write; tab contract fixture; README; buffer | Final sign-off |

**What actually happened (24 Oct):** the plan ran ahead of the calendar. Ingest, snapshot, metrics, theses, Skeptic, advice, alerts, EDGAR, price history, fund health, digest and look-through were all built between 21 and 24 Oct, with the real data run end to end each day. What the plan called Day 6 (replay test) is done; perturbation tests, golden theses and the Supabase write remain. The M1 review below is still the gate before WealthLens integration.

**25 Oct:** fund files for SBI Contra, Invesco and Bandhan were read (PDF and spreadsheet), conviction tiers were set for all 19 stocks, and the Researcher was built: `fetch-docs` for EDGAR and Screener-listed India documents, transcript validation, and the stricter ADD rule. Real filings moved 17 of 19 theses to MEDIUM. That turned four REVIEW labels into ADD (VBL, ACE, IEX, M&M) and changed no trim. Also built 25 Oct: perturbation and golden tests, and quarterly drivers (code-owned WATCH drivers from the newest quarter against the same quarter a year earlier, rebuilt every run). Also built 25 Oct: reverse DCF and sector percentiles (US peer groups live). Open: nothing blocking sign-off; India percentiles are deliberately skipped. The agenda for the review is in `M1_REVIEW_AGENDA.md`.

**3-day cut (if capacity drops):** Days 1 to 3 give the portfolio risk view, data-quality report, action labels for concentration and dust, and theses for the top 8 positions, with no Skeptic and no alerts.
**5-day cut:** adds the Skeptic, alerts, hysteresis and the full report, without the Supabase write.

**Cut order if time runs short:** (1) fund look-through, (2) Supabase write, (3) India closest-peers cohort, (4) Telegram digest. **Never cut:** thesis versioning, REAFFIRM/AMEND/REPLACE, evidence IDs, the replay test.

**M1 review rubric:** for each of the 25 positions: (a) can you say in one sentence why Parakh recommends this action? (b) is every claim in the case file traceable to a source? (c) did running twice give the same answer? (d) is anything stated confidently that the data cannot support? M1 passes with at least 22 of 25 clean and no (d) failures on the top 8 positions by value.

**Honest schedule risks, in order:** (1) data plumbing for the US sources and the manual Screener exports, not the coding; (2) review latency, since I am blocked while a question waits; (3) cost-basis source; (4) LLM output variance on young listings. A 7-day finish is realistic. A 3-day finish delivers the risk view and an early thesis set, not the whole system.

---

## 12. Testing

| Test | What it proves |
|---|---|
| Contract tests | The real export and edge-case fixtures parse into `holdings.v2` |
| DQ tests | Each DQ rule fires on the case it should (including the TSLA ratio) |
| Metric tests | Code metrics match an independent spreadsheet for 3 golden stocks |
| Matrix tests | Every cell of §7.3 produces the stated action; hysteresis buffers hold |
| **Replay test** | Same inputs twice give an identical stance and action |
| **Perturbation test** | A small price move or an irrelevant filing does **not** change the thesis |
| **No-evidence-no-change test** | An LLM output that changes a thesis without new dated evidence is rejected |
| Citation test | Every driver and risk resolves to an evidence ID |
| LLM mocked in CI | No network in tests; live runs only by hand |

**Status:** 129 tests pass. Replay is tested at unit level and on your real theses (identical rerun: 0 alerts; edited prior state: exactly the expected change alerts). Matrix, citation and no-evidence-no-change tests exist. Added 25 Oct: filing fetch and parsing (EDGAR layouts, Screener page, blocked-download list, transcript validation and fallback). Still to do: perturbation test and golden-thesis checks against an independent spreadsheet.

---

## 13. Risks and honest limits

1. **No evidence yet that this advice adds value.** An LLM thesis built on public filings is a structured second opinion, not an edge. The system keeps an **advice journal** (every label, date and price) so you can judge it after a few quarters. It makes no performance claim.
2. **Consistency can become stubbornness.** Burden-of-proof rules protect against flip-flopping but can delay a real change. The asymmetric downgrade rule and the Skeptic exist to offset that.
3. **Valuation is weak for pre-profit and young companies** (several of your Indian listings, and arguably TSLA). Those get INSUFFICIENT or LOW confidence rather than a forced answer.
4. **US sources are unofficial or untested** (yfinance, transcripts). Provenance and fallbacks limit the damage, and the Day 2 spike will tell us how much.
5. **Sector classification is noisy**, so percentiles are shown with their cohort.
6. **Staleness.** Advice is only as current as the last WealthLens sync. The banner makes this visible, and a stale-position advisory is downgraded to REVIEW.
7. **Regulatory.** For your own use this is a personal analytical tool. You said others will use it (Q7), including through WealthLens. Giving hold/trim/exit advice on named securities to people other than yourself, particularly for any consideration, may fall under SEBI's Investment Adviser regulations in India. **Get qualified advice before anyone beyond your household uses it.** This design is ready for that: every table is scoped by `user_id`, policy is per user, nothing personal is hard-coded, and every screen carries the advisory notice. I am not a lawyer.
8. **Observed in the first real runs (24 Oct).** (a) The model's thresholds were too lenient, and its choice of drivers varied between runs; code now adds hygiene drivers and tightens warn lines (§6.3). (b) Roughly 3 of 19 thesis calls returned malformed output per run; retries handle it. (c) *Resolved 25 Oct:* theses now cite filings (see §6.3).  (d) Valuation against a stock's own history rewards a stock that has always been expensive; AMZN reads CHEAP at 29% below its own median while still trading on a high multiple. Treat the label as one input. (e) *Found 25 Oct:* the metric drivers are computed from fiscal-year data while the filings show the newest quarters, so a thesis can read INTACT while the Skeptic cites deteriorating quarters (META's Q3 operating margin 20% against 40% a year earlier; AMZN and GOOGL trailing free cash flow and capex; trailing profit 1.5x to 1.8x the fiscal year for AMD, AMZN, GOOGL and NVDA). *Built 25 Oct:* quarterly drivers (`q_sales_yoy`, `q_np_yoy`, `q_npm_chg`, `q_np_down_run`) add code-owned QM drivers that raise WATCH while the newest quarter is adverse (revenue down year on year; profit down over 25%; net margin down over 5 points; profit lower than a year earlier three quarters running). They are rebuilt each run, never BROKEN, and never alter the model's frozen drivers. Thresholds are blunt by design; a one-off shows as WATCH for the reader to judge. The META and AMZN trims are driven by the concentration cap, so the advice there holds either way. (f) Indian exchange documents are not available to programs, so India transcripts need a manual download step each quarter (about two per stock).
9. **Family portfolios.** Four members appear in the export. Advising on someone else's holdings should be with their knowledge.

---

## 14. Archive and cut-over

Done in this change:
- `FRAMEWORK/00–18` and the old README moved to `FRAMEWORK/archive/v1_universe_engine/` (OneDrive copy and the Claude project copy).
- This document and a new README are the live set.

For you, in PowerShell, when you are ready (nothing here is run for you):

```powershell
Set-Location "C:\Users\atall\OneDrive\Documents\AI Experiments\Stock Analysis\parakh"
git tag v1-final
git push origin v1-final
# Add a "Superseded by parakh-advisor" note at the top of README.md, then:
git add README.md
git commit -m "docs: mark v1 as superseded by parakh-advisor"
git push
```

Leave the `ORACLE` folder and the Supabase `parakh` project untouched until v2 is signed off.

---

## 15. Decision log (v2)

| ID | Decision | Status |
|---|---|---|
| V2-01 | Pivot from universe engine to portfolio advisory; v1 archived | **Decided (you)** |
| V2-02 | Input is the WealthLens portfolio; output goes into a future WealthLens tab | **Decided (you)** |
| V2-03 | Thesis must be consistent; changes raise alerts; advice only | **Decided (you)** |
| V2-04 | Cost basis included; tax excluded | **Decided (you)** |
| V2-05 | Explicit labels (hold, trim, add, exit) | **Decided (you)** |
| V2-06 | Quarterly plus event-driven cadence; Telegram only on thesis change | **Decided (you)** |
| V2-07 | Multi-user: others will use it later | **Decided (you)**; see risk 7 |
| V2-08 | Peers: whole sector where data allows | **Decided (you)**; India adjusted per §8 |
| V2-09 | New repo in the same root; old repo frozen | **Decided (you)**: "rewrite or new repo" |
| V2-10 | US stocks in scope | **Decided (you), 21 Oct** |
| V2-11 | Policy defaults in §7.2 (10% single-name, 35% top-3) | **Decided (you), 21 Oct**; the US discount rate is still open |
| V2-16 | Cost basis for Indian stocks and funds stays "cost pending" for now; add a source later if it changes a decision | **Decided (you), 21 Oct** |
| V2-17 | Scope is all four members combined, with a member filter | **Decided (you), 21 Oct** |
| V2-12 | Tier: Proto plus selected Production items | **Decided (you), 21 Oct** |
| V2-18 | Repo `parakh-advisor` beside `parakh` | **Decided (you), 21 Oct** |
| V2-19 | Reverse-DCF discount rate: US 10%; India 15% (v1 carry-over) | **Decided (you), 21 Oct** for US |
| V2-13 | Funds get a health card and overlap, not a thesis | **Proposed** |
| V2-14 | No MCP server, orchestrator or Streamlit in v2 | **Proposed** (revisit after M1) |
| V2-15 | HTML report as the tab prototype; no separate UI built | **Proposed** |

| V2-20 | LLM provider: Anthropic API, model `claude-sonnet-5-5` (`ANTHROPIC_API_KEY` in `.env`) | **Decided (you), 23 Oct** |
| V2-21 | Code, not the model, adds hygiene drivers and tightens warn lines at thesis creation | **Decided (build), 23 to 24 Oct**; see §6.3 |
| V2-22 | Conviction is unset by default; only the concentration cap applies until you set it | **Decided (build), 24 Oct** |
| V2-23 | Valuation v1 = P/E against own history, fiscal-year P/E when trailing profit is inflated | **Decided (build), 24 Oct**; weak anchor, to be replaced |
| V2-24 | Fund verdict thresholds: 3 points a year behind over 3 years = LAGGING | **Proposed**, your call |
| V2-25 | Telegram digest is opt-in (`--send`); nothing is sent by default | **Decided (build), 24 Oct** |
| V2-26 | Delivery: files written straight into the `parakh-advisor` folder; `CHANGELOG.md` records every change | **Decided (you), 23 to 24 Oct** |
| V2-27 | Thesis folders are named by symbol, not ISIN | **Decided (you), 24 Oct** |
| V2-28 | Filings auto-fetch: SEC EDGAR for US; Screener-listed links for India; documents the exchange refuses are listed for manual download, never worked around | **Decided (you), 25 Oct** |
| V2-29 | `fetch-docs --browser-headers` exists as an opt-in for exchange downloads; off by default; never used for EDGAR or Screener | **Decided (you), 25 Oct** |
| V2-30 | ADD needs MEDIUM or higher confidence and a readable CHEAP or FAIR valuation; trims are not gated by confidence | **Decided (you), 24 to 25 Oct** |
| V2-31 | A downloaded transcript must pass validation (length, concall words, readable text); a failure falls back to an older call and the stale choice is flagged | **Decided (you), 25 Oct** |
| V2-32 | A filing counts as a source for confidence only within 400 days of the newest evidence | **Decided (build), 25 Oct** |

**Change control:** any new idea goes to `BACKLOG.md`. It enters the build only if it changes a decision you make with money, at the frequency you make it. The backlog is reviewed once, after the M1 review.

---

## 16. Open questions

| # | Question | Status |
|---|---|---|
| Q1 | Are US stocks in scope? | **Answered 21 Oct: yes** |
| Q2 | Cost basis for Indian stocks and funds | **Answered 21 Oct: leave as "cost pending"** (P&L column blank for those rows) |
| Q3 | Whose holdings? | **Answered 21 Oct: all members combined, with a filter** |
| Q4 | Policy defaults in §7.2 | **Answered 21 Oct: 10% single-name, 35% top-3, US discount rate 10%** |
| Q5 | Tier | **Answered 21 Oct: Proto plus selected Production items** |
| Q6 | Repo name and location | **Answered 21 Oct: `parakh-advisor` beside `parakh`** |

| Q7 | Conviction tier for each holding (core, standard, starter, tracking) | **Answered 24 Oct:** set for all 19 stocks in `config/instruments.yaml` |
| Q8 | Is Tesla's recorded cost ($12.13 a share) split-adjusted or wrong? | **Answered 24 Oct:** split-adjusted and correct; DQ-04 is marked accepted in `instruments.yaml` |
| Q9 | Fund portfolio files for look-through | **Answered 24 Oct:** PPFAS, JioBlackRock, SBI Contra, Invesco and Bandhan are in `data/inbox/funds/`. Nippon is exited; it leaves with the next CAS |
| Q10 | Are 3 points a year behind the benchmark the right line for LAGGING? | **Open** |
| Q11 | Move Regular-plan funds to Direct? | **Yours**; depends on tax and exit load, which the system does not compute |

No blocking questions remain for testing. Build started Day 1 (Thu 22 Oct plan, begun early on 21 Oct).
