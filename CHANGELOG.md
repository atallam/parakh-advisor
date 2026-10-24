# Changelog

Newest first. Every change to this folder is listed here, so you can see what moved without diffing.

## 2026-10-24 - Day 10: SBI Contra, Invesco Smallcap and Bandhan Small Cap portfolio files
- Added your SBI Contra (Sep 2026), Invesco India Smallcap (Sep 2026) and Bandhan Small Cap (30 Sep 2026) portfolio files to `data\inbox\funds`. Nippon India Small Cap is not needed: you have exited it (see "To do" below).
- New: the reader handles a single-scheme PDF with a "Name of the Instrument | % to NAV" table in three side-by-side columns (Bandhan). Industry headings (bold, they carry the sum of their stocks) are skipped, wrapped names are joined, PDF ligature gaps ("Scienti fi c") are closed, cash and grand-total lines and the chart below the table are ignored. Result: 263 holdings, 87.0% of the fund (stated equity 86.4% plus 0.6% REIT).
- Fix: SBI-style sheets list T-bills, index futures, options, margin money and side tables (derivative expiry dates, quantities) below the portfolio, and the side-table numbers looked like weights. Equity lines only are kept now (a line with an ISIN must hold a real ISIN; government-security ISINs, negative weights and the derivative lines are dropped). SBI Contra reads 88 lines, 92.0% of the fund.
- Fix: the scheme name is now taken from the "Scheme name" label (SBI) or the first line of the title cell (Invesco), and an AMC-only name such as "INVESCO MUTUAL FUND" is no longer used as the title.
- Fix (affects the numbers): a holding with an Indian ISIN that is not one of yours was still matched by name, so "Mahindra & Mahindra Financial Services" (SBI Contra, 1.95%) counted as Mahindra & Mahindra. Names are now matched only for lines with no ISIN, a foreign ISIN or the overseas marker.
- Tests: 3 new in `tests/test_funds.py` (AMC sheet junk, title rules, column PDF) and 1 for the ISIN rule. The 17 tests in that file pass; the whole suite was not run (my sandbox on your laptop is out of disk), so run `uv run pytest` once.
- To do: your WealthLens export (21 Oct) still lists Nippon India Small Cap as active. Mark it exited in WealthLens and re-export, otherwise the report still counts it.

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
