# Changelog

Newest first. Every change to this folder is listed here, so you can see what moved without diffing.

## 2026-10-25 - Day 16: `advisory.v1` output and Supabase write
- **Contract (`contracts/advisory_v1.py`):** seven tables from design 9.3 (`advisory_runs`, `_theses`, `_drivers`, `_actions`, `_alerts`, `_evidence`, `_portfolio`) built as plain row models from a finished run. IDs come from the content (uuid5), so the same run always has the same ids and publishing twice changes nothing. `created_at` on derived rows is the data date, so the same inputs give the same rows. `advisory_evidence` is in the schema but not filled yet.
- **Tables and security (`supabase\advisory_v1.sql`):** run once in the Supabase SQL editor. Row level security on every table (you can read only your own rows), no deletes, only alert acknowledgement may be updated, plus two views of current state (`advisory_current_theses`, `advisory_current_actions`).
- **Writer (`publish/supabase.py`):** inserts only, ignoring duplicates, 200 rows per call, `advisory_runs` written last as the "this run is complete" marker, so a half-failed publish shows nothing and re-running is safe. Uses `SUPABASE_URL`, `SUPABASE_KEY`, `PARAKH_USER_ID` from `.env`. Not run against a real Supabase yet (needs your project and key): tested with a recording stand-in.
- **CLI:** `advise` now always writes `out\advisory_v1.json`; add `--publish` to send it to Supabase.
- **Contract test (`tests\test_advisory_contract.py`, frozen shape in `tests\fixtures\advisory_v1_shape.json`):** removing or retyping a column, or adding one, fails the test until the contract version is bumped. Also checks ids are unique and per user, drivers point at their thesis, runs are written last, no secret leaks into rows, and the SQL file defines every table with row level security.
- Tests: 223 passing (14 new).

## 2026-10-25 - Day 15: reverse DCF and sector percentiles
- **Reverse DCF (`metrics/rdcf.py`):** new metrics `rdcf_growth` (the yearly profit growth today's market value asks for over 10 years) and `rdcf_gap` (that minus the growth the company delivered; past growth above 25% is capped). Rates: US 10% discount and 3% terminal, India 15% and 5%; profit (lower of last fiscal year and trailing four quarters) stands in for free cash flow. Solved by bisection; limits of the search are reported, not hidden. Loss-making companies are n/a with a reason.
- **Valuation label is now the more cautious of two readings** (`advice/valuation.py`): own-history P/E and the reverse DCF. Gap -8 or less CHEAP, up to +5 FAIR, +5 to +12 RICH, more than +12 STRETCHED; any ask above 25% a year is STRETCHED. One reading alone still gives a label and says so; NA only when both are unreadable. For a company whose history is flagged unreliable (HDFC Bank) only the absolute ask counts. Live check on the 8 US holdings: AMD, TSLA, ELF STRETCHED; GOOGL RICH; NVDA, META, AMZN, SOFI FAIR. AMZN moves from CHEAP to FAIR; SOFI becomes readable.
- **Sector percentiles (`metrics/peers.py`, `sources/peers.py`, `config/peers.yaml`):** each holding can name a peer group (`peer_group:` in instruments.yaml). Peers run through the same metric code. Quality percentile = average rank of revenue growth, ROCE, operating margin, debt/equity and cash conversion (banks: revenue growth, profit growth, ROE); needs 5 or more usable peers and 3 or more measures, else it says why there is none. Top third (66.7+) lets an INTACT thesis read STRONG. A P/E percentile is shown as information only. The holding is never in its own cohort. Both appear as evidence (`MET.sector_quality_pct`, `MET.sector_pe_pct`) with the cohort name and size.
- Starter US groups for AMD/NVDA, META/GOOGL/AMZN, TSLA, ELF and SOFI are in `config/peers.yaml`: edit them. India groups need 8 to 12 Screener exports per group in `data\inbox\peers\<group>\` (not set up yet).
- New option: `thesis --peers <file>` and `--no-peers`. The first `thesis` run downloads about 50 peers' filings and prices (roughly 3 to 5 minutes, then cached: 7 days for filings, 1 day for prices) and re-runs every stock because the inputs changed.
- Fix found on the way: YAML reads a bare `ON` ticker as "true"; the peer loader now refuses such values with a clear message.
- Tests: 209 passing (36 new).

## 2026-10-25 - Day 14: quarterly drivers
- **Why:** the annual drivers lag by up to a year, so a thesis could read INTACT while the newest quarter had already turned (META's operating margin fell from 40% to 20%, AMD, AMZN, GOOGL trailing profit well above the fiscal year).
- **New metrics (`metrics/quality.py`), each against the same quarter a year earlier so seasonality cancels:** `q_sales_yoy`, `q_np_yoy`, `q_npm_chg` (net margin change, points), `q_np_down_run` (consecutive quarters with lower profit than a year earlier, max 4). Works for India (Screener quarters) and US (10-Q, Q4 derived). N/A with a reason if there is no quarter a year earlier or the year-ago profit was not positive.
- **New code-owned drivers `QM1..` (`thesis/rules.py`):** added when the newest quarter is adverse, rebuilt on every run, gone when the quarter recovers. Lines: revenue below a year earlier; profit down more than 25%; net margin down more than 5 points; profit lower than a year earlier three quarters running. They only raise WATCH (stance WEAKENING, so no adds), never BROKEN, and never touch the model's frozen drivers. Skipped if the model already monitors that indicator.
- Effect on advice: a deteriorating quarter now stops an ADD and, if the stock is also RICH, can lead to TRIM. Thresholds are deliberately blunt; a one-off (tax, write-down) shows as WATCH and the reader judges it.
- **Added after the first real report (25 Oct):** a one-off in the year-ago quarter can hide a collapse (META's Sep 2025 quarter carried a tax charge, so Sep 2026 profit read +264% while it had halved from the two quarters before, and META stayed STRONG). New metric `q_np_vs_med4` (the latest quarter's profit against the median of the previous four) and a driver: profit should not be more than 40% below that median. Checked on the 8 US holdings: only META trips it (-49%).
- The first `thesis` run after this will re-run every stock (new evidence changes the input fingerprint).
- Tests: 173 passing (12 new in `tests\test_quarterly.py`).

## 2026-10-25 - Day 13: perturbation and golden tests
- **Golden metrics:** four made-up companies (healthy, bank, loss-making, one-off trailing gain) in `tests\golden\golden_metrics.xlsx`, with plain spreadsheet formulas written from the metric definitions, not from the code, and calculated by LibreOffice. The code agrees with the spreadsheet on all 16 metrics for all four (bank-only gaps included). `python tests/golden/build_golden.py` rebuilds it if the inputs change.
- **Perturbation tests (`tests\test_consistency.py`):** the advice label changes along the weight axis only at a declared threshold (dust, band edges, the cap, cap minus buffer) and never flickers back; hysteresis holds a concentration trim between 8% and 10%; a 1% price move keeps every valuation band and flips one exactly at its edge; an irrelevant new filing, a 1% price move or a re-run leave the thesis unchanged; evidence order does not change the digest; a stale filing cannot lift confidence; row order and a uniform 1% price rise change no weight or label.
- Checked that the tests can fail: five deliberate breaks (hysteresis removed, a stray threshold, ROE on year-end instead of average equity, the inflated-profit rule dropped, filing age ignored) were each caught.
- No code behaviour changed; no bug was found by these tests. Note for the record: a bank has no `op_margin_chg` metric at all (rather than an empty one).
- Tests: 161 passing.

## 2026-10-24 - Day 12: automatic filing download (`fetch-docs`)
- New command `parakh-advisor fetch-docs` fills `data\inbox\research\<SYMBOL>\` for you. Run it, then `thesis`, then `advise --online`.
- US (fully automatic, SEC EDGAR): the last 3 earnings releases and the management discussion of the latest 10-Q/10-K.
- India: concall transcripts and results announcements are found on each stock's public Screener page (one page per company, cached a day, 1 second pause). The exchange often answers 403 to programs. That is never worked around: those documents are listed in `TO_DOWNLOAD.txt` in the stock's folder with a suggested file name (`YYYY-MM-DD_concall-transcript.pdf`). Save them from your browser into that folder and the next `thesis` run reads them.
- Already-fetched documents are skipped, so re-running is cheap. Add `--only META` to fetch one stock.
- PDFs in the research folder are now read with pdfplumber (handles the exchange PDFs better).
- A filing only counts as a source for confidence if it is within about 13 months of the newest data, so a stale filing cannot lift a thesis to MEDIUM.
- Optional `screener_code` in `instruments.yaml` for stocks whose Screener URL differs from the symbol (e.g. M&M).
- Wording fix: "no readable valuation" now says too little history, losses, or distorted earnings (it was "young or loss-making", wrong for HDFC Bank).
- Transcript checks ported from the old Parakh: a download must look like a real concall (length, concall words, readable characters, normal word length), otherwise it is rejected with the reason and the next-older call is tried (up to 4 tries, 2 kept). If the newest call has no usable transcript the run says so ("treat the management commentary as stale"). Long transcripts keep the opening remarks and the whole Q&A.
- `fetch-docs --browser-headers` (off by default): sends browser-style headers for India document downloads only, for when the exchange refuses the default request. Never used for SEC EDGAR or the Screener page.
- Fix: thesis replies were capped at 3000 tokens, so a long AMEND (full thesis plus verbatim quotes from the new filings) was cut off mid-sentence and failed as "invalid JSON" (NVDA, META, GOOGL). The cap for theses is now 8000, and a cut-off reply is reported as such.
- Fix: the model sometimes appends stray text (empty tool-call tags) after a valid JSON reply; that failed NVDA's Skeptic step. The reader now takes the first complete JSON object and ignores what follows (text before the object is still an error).
- Fix: US filings were not being found for AMD (and by extension most US names). The exhibit is now found by the type the filing's own index page gives it (EX-99.1) instead of by file name (AMD calls it `q22026991.htm`), and the 10-Q/10-K MD&A heading now tolerates table bars and curly apostrophes ("ITEM 2. | MANAGEMENT'S"). Checked live: AMD, META, NVDA, TSLA, SOFI, ELF, AMZN and GOOGL each return 3 earnings releases and the latest MD&A.
- Tests: 129 passing.

## 2026-10-24 - Day 9b: JioBlackRock Flexi Cap portfolio file
- Added your JioBlackRock Flexi Cap Fund September 2026 portfolio (138 equity lines, 97.84% of the fund) to `data\inbox\funds`.
- The reader now takes the scheme name from the top of the file, so a file is matched to your fund even when its file name is opaque.
- "Net Receivables / (Payables)" is no longer counted as a holding.
- Result: HDFC Bank now shows via both flexi caps (1.2% in total), M&M too; SHADOWFAX, ATHERENERG, GROWW appear via JioBlackRock.
- Tests: 106 passing.

## 2026-10-24 - Day 9: fund factsheets (PDF) and index-fund files
- Look-through now also reads fund-house factsheet PDFs (tested on the PPFAS September 2026 factsheet: Parag Parikh Flexi Cap Fund, 90.2% of the fund read, including Alphabet 4.29%, Meta 2.83%, Microsoft 2.48%, Amazon 2.30%). The factsheet covers many funds; each is matched to yours by the scheme name printed in it. New dependency: `pdfplumber` (installed automatically by `uv run`).
- Excel reader accepts "Market Value %" headers and drops the scheme's own 100% row and cash lines (found on a real JioBlackRock file).
- A file whose weights add up to under 50% or over 105% is not used, and the report says so.
- Result on your data: Parag Parikh adds only about 0.1% each to META, AMZN and GOOGL (your holding in it is 2.5% of listed equity). The concentration problem is the direct holdings, not the funds.
- Tests: 105 passing.

## 2026-10-24 - Day 8b: say so when nothing changed
- `advise` report now shows "Alerts (0): No changes since the last run" instead of leaving the section out. The plain `snapshot` report is unchanged (it has no previous run to compare with).
- Tests: 103 passing.

## 2026-10-24 - Day 8: quiet reruns, Telegram digest, fund look-through
- Fix: "Position far above the cap" was raised on every run. It now fires once, when the position first goes more than 5 points over the cap (new `far_over_cap` field in `data/advice/state.json`; your first run after this update may raise it once more).
- Replay test: an identical rerun gives 0 alerts; changed state gives exactly the change alerts (advice change, driver moved, thesis downgraded; upgrades need two consecutive runs). Checked on your real theses and as unit tests.
- Digest: every `advise` run writes `out/digest.txt` (plain text: alerts, then advice by label, then the top issue). Add `--send` to post it to Telegram; needs `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. Nothing is sent without `--send`; a send failure is a warning, not an error.
- Fund look-through (with `--online`): put each fund's monthly portfolio file (xlsx or csv from the fund house site) in `data/inbox/funds/`, named with the fund's name. The reader finds the header row itself. The report adds "What your funds also hold": per direct stock, % direct + % via funds, true US exposure including funds, and fund pairs that hold the same companies. Missing or unmatched files appear in "Not fully analysed".
- Tests: 102 passing.

## 2026-10-24 - Day 7a: fund health card and category overlap
- New `funds/health.py` and `advice/funds.py`. With `--online`, each equity fund gets a health card from AMFI NAV history (mfapi.in, cached one day): 1/3/5-year returns against an index-fund benchmark (Nifty Smallcap 250 for small-cap funds, Nifty 500 for the rest), how often it beat the benchmark in rolling one-year windows, volatility and worst fall, and for Regular plans the measured return gap to the same scheme's Direct plan.
- Verdict is a rule: HEALTHY (ahead and winning at least half the windows), WATCH (behind by less than 3 points a year over 3 years), LAGGING (3 or more points a year behind, advice REVIEW), TOO_NEW (under 3 years, e.g. JioBlackRock), NO_DATA.
- Report: fund rows show the verdict, benchmark and numbers; a "Fund overlap by category" box lists categories held through 2+ funds (2 flexi cap = 9.8% of listed equity, 3 small cap = 7.5%); the summary notes lagging funds and Regular plans costing extra.
- Not done yet: stock-level overlap (needs the funds' portfolio files).
- Tests: 95 passing.

## 2026-10-24 - Day 6b: conviction unset by default, clearer valuation text
- Fix: until you set `conviction:` for a holding in `config/instruments.yaml`, it is "unset" and only the concentration cap applies. Before, every holding defaulted to "tracking" (a 0-1% band), so any rich-valued stock above 1% got TRIM (this is why GOOGL turned TRIM). Setting `conviction: tracking` yourself still means 0-1%.
- Valuation text now says which P/E was compared (trailing, or fiscal-year when trailing profit is inflated).
- Tests: 89 passing.

## 2026-10-24 - Day 6a: US price history and valuation
- New `sources/us/prices.py`: monthly prices and stock splits from Yahoo's chart endpoint (cached one day, paused between calls, retried on rate limits, older cache used if Yahoo is down).
- US P/E history: fiscal-year-end price (split effects undone, so it matches the share count reported at the time) divided by EPS from as-first-reported diluted shares. US stocks now get a cheap / fair / rich / stretched label like the Indian ones.
- Valuation rule: if trailing 4-quarter profit is more than 1.4x last fiscal year's (often one-off gains, as at GOOGL, AMZN and NVDA), the comparison with history uses the fiscal-year P/E and says so, so a one-off cannot make a stock look cheap.
- No need to delete theses: valuation is calculated fresh by `advise`. Run `advise` only.
- Tests: 88 passing.

## 2026-10-24 - Day 5d: retry on malformed model output
- `thesis` retries a company up to 3 times when the model's output is rejected (a different company failed on each run, which points to occasional malformed output), prints the reason for each attempt, and ends with a list of any that still failed.

## 2026-10-24 - Day 5c: readable thesis folders
- `data/theses/` folders are now named by symbol (AMD, GROWW, MAZDOCK) instead of ISIN. Existing ISIN-named folders are renamed automatically on the next run, contents untouched, so you do not need to delete anything for this.
- Tests: 86 passing.

## 2026-10-24 - Day 5b: tighter theses, visible failures
- Thresholds: at creation, code pulls any warn line more than 30% from today's value back to 30% (the Skeptic kept calling them lenient); the break line stays beyond it. Noted in the driver text.
- New code-added hygiene drivers: return on equity below 10%, and trailing P/E above 60x. Both warn-only, so AMD, TSLA, ELF and similar names become WEAKENING ("no additions") instead of INTACT.
- New profile `broker` skips the cash-conversion driver (client money distorts it). Set `profile: broker` on GROWW in `config/instruments.yaml` (a command below does it).
- `advise`: load failures and holdings with fundamentals but no thesis are printed at the top of the console output and shown as a "Not fully analysed" box in the HTML.
- First run: many "New thesis created" alerts collapse into one baseline summary.
- Tests: 85 passing.
- Delete `data\theses` and `data\advice` and re-run `thesis`: the rules for new theses changed.

## 2026-10-24 - Day 5a: US stocks from SEC EDGAR
- New `sources/us/edgar.py`: annual and quarterly fundamentals for your 8 US stocks from SEC company facts (USD millions), shaped like a Screener company so metrics, theses, Skeptic and advice run unchanged. Only real fiscal years are used (10-Q trailing-twelve-month windows are ignored); Q4 is derived as year minus Q1-Q3.
- New `sources/companies.py` loads India (Screener) and US (EDGAR) together; `thesis`, `metrics` and `advise` all use it. US market cap = your WealthLens price x shares outstanding.
- `config/instruments.yaml` now lists the 8 US stocks (`edgar:` ticker). SoFi uses the bank profile.
- Set `PARAKH_CONTACT=your email` in `.env`: SEC rejects anonymous requests (HTTP 403).
- Known limits: no price history yet, so valuation is NA for US stocks; debt excludes operating leases; trailing profit includes investment gains for AMZN, GOOGL, META.
- Tests: 81 passing.

## 2026-10-23 - Day 4d: report fixes (from your advice.html)
- TRIM notes again show the share vs the cap and the rupee amount above it (lost in 4c).
- Fund rows no longer repeat their long name; the "valuation basis: no fundamentals loaded" line is hidden.

## 2026-10-23 - Day 4c: advice and alerts
- New command `parakh-advisor advise --input data\inbox\holdings.json [--online]`: stance x valuation x your policy -> ADD / HOLD / TRIM / EXIT / REVIEW / BUILD OR CONSOLIDATE, with reasons and "what would change this".
- `advice/matrix.py` (pure decision matrix, 2-point hysteresis on leaving a concentration TRIM), `advice/valuation.py` (trailing P/E vs own 5-year median; NA when unreliable), `advice/apply.py`.
- `alerts/changes.py`: High/Medium/Low alerts on stance change, kill-criterion trip, driver flip, action change, far above cap. Slow-upgrade rule: an upgrade must appear on two consecutive runs. State saved in `data/advice/state.json` (`--dry-run` leaves it untouched).
- `config/instruments.yaml` gains `conviction` (default tracking; only core/standard can ever be ADD) and `valuation_history_reliable` (false for HDFC Bank).
- Report: alerts section, stance/valuation/reason per position, expandable "why and what would change" with the Skeptic's counter-case.
- Tests: 77 passing.

## 2026-10-23 - Day 4b: red flags are not left to the model
- New `hygiene_drivers` (rules.py): when a thesis is created, code adds a monitored driver for weak cash conversion, interest cover under 1.5x, negative trailing profit, or P/E over 30% above its own median, unless a driver already covers that metric. Raise WATCH only, never BROKEN.
- Found on Mazagon Dock: two fresh runs differed because the model picked different drivers.
- Tests: 65 passing.

## 2026-10-23 - Day 4a: Skeptic
- New `agents/skeptic.py` + prompt: a tool-using loop (metric, peers, search_docs, get) capped at 4 tool calls; writes the counter-case only and cannot change drivers or stance. Evidence ids it cites are checked in code.
- `thesis` command runs it for new or changed theses and fills `skeptic_counter_case`; unchanged evidence carries the previous counter-case forward. `--no-skeptic` skips it.
- "peers" is your own 11 holdings, labelled as such, not a sector (proper sector cohorts come later).
- Tests: 63 passing.

## 2026-10-23 - Day 3c: Researcher v1 (documents you supply)
- New `research/documents.py`: put results releases, call transcripts or filings in `data/inbox/research/<SYMBOL>/` named `YYYY-MM-DD_name.txt|md|pdf`; they become dated, citable passages.
- Qualitative drivers can move to WATCH only with a quote that appears word for word in a cited passage; BROKEN/OK from the model is refused and logged. Confidence is no longer capped at LOW once a thesis has document evidence.
- `thesis` command prints how many passages each stock had.
- Tests: 58 passing.

## 2026-10-23 - Day 3b: review fixes
- Stance: a company that is loss-making now and has fewer than 2 profitable years is INSUFFICIENT, not INTACT (Ather was INTACT while losing Rs 517 cr).
- Prompt: no raw evidence ids in prose (Shadowfax); prefer ratios over absolute rupee thresholds (HDFC Bank profit floor).
- Stance: any driver on WATCH or BROKEN now gives WEAKENING (was INTACT with one WATCH). Found on the IndiGo thesis.
- Confidence is LOW for theses with no filing or quoted source ("numbers-only"), until the Researcher exists.
- New metrics: net profit (FY and trailing 4 quarters) and loss-making quarters, so a loss is stated, not hidden behind n/a.
- Prompt: no speculation about why a number is what it is without evidence.
- Delete `data\theses` and re-run: the rules for pre-registered theses changed.

## 2026-10-23 - Day 3: theses
- Added `thesis/` (models, evidence, rules, store), `agents/thesis_analyst.py` and its prompt, `llm/client.py`.
- New command: `parakh-advisor thesis [--only TEXT]` (needs ANTHROPIC_API_KEY in .env).
- Fix: Anthropic client retries without `temperature` when the SDK or model rejects it.
- Tests: 51 passing.

## 2026-10-23 - Day 2: data
- Added fund lookup by scheme code (`sources/funds/mfapi.py`), `--online` on `snapshot`; gold ETFs move to the commodity sleeve.
- Added Screener export reader and `metrics/quality.py`; new command `parakh-advisor metrics`.
- Added `config/instruments.yaml` (ISIN to Screener name, sector, profile).
- New data-quality flag DQ-09 (Regular plan held).

## 2026-10-21 - Day 1: snapshot
- WealthLens JSON import, data-quality flags DQ-01..08, risk snapshot, HTML report.
