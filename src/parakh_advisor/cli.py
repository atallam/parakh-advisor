"""Command line: `parakh-advisor snapshot --input data/inbox/holdings.json`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from parakh_advisor.advice.policy import load_policy
from parakh_advisor.advice.snapshot import build_snapshot
from parakh_advisor.agents import skeptic, thesis_analyst
from parakh_advisor.alerts.changes import collapse_baseline
from parakh_advisor.ingest.instruments import acknowledged_flags, load_instruments
from parakh_advisor.ingest.normalise import build_portfolio
from parakh_advisor.ingest.wealthlens_json import ExportError, load_rows
from parakh_advisor.llm.client import AnthropicLLM, LLMError
from parakh_advisor.metrics.peers import sector_context
from parakh_advisor.metrics.quality import compute
from parakh_advisor.report.html import render_snapshot
from parakh_advisor.research.documents import load_documents
from parakh_advisor.sources.companies import load_companies
from parakh_advisor.sources.funds.mfapi import MfapiResolver
from parakh_advisor.sources.peers import PeerLoader, load_peer_groups
from parakh_advisor.thesis.evidence import from_metrics
from parakh_advisor.thesis.store import ThesisStore


def cmd_snapshot(args: argparse.Namespace) -> int:
    try:
        rows = load_rows(args.input)
        resolver = MfapiResolver(args.cache) if args.online else None
        portfolio = build_portfolio(rows, fund_resolver=resolver)
        policy = load_policy(args.policy)
        snap = build_snapshot(
            portfolio,
            policy,
            member=args.member,
            acknowledged=acknowledged_flags(load_instruments(args.instruments)),
        )
    except (ExportError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_snapshot(snap), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(snap.model_dump_json(indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    for line in snap.verdict:
        print(f"  - {line}")
    return 0


def _portfolio_or_none(path: str):
    """Holdings give US prices (market cap). If the export is missing, US stocks are skipped, not guessed."""
    try:
        return build_portfolio(load_rows(path))
    except (ExportError, ValueError, OSError):
        print(
            f"  note: could not read {path}; US stocks need it for prices and will be skipped",
            file=sys.stderr,
        )
        return None


def cmd_metrics(args: argparse.Namespace) -> int:
    instruments = load_instruments(args.instruments)
    companies = load_companies(
        instruments, args.screener, _portfolio_or_none(args.input), args.cache
    )
    if not companies:
        print(
            "error: no fundamentals could be loaded (check data/inbox/screener and your network)",
            file=sys.stderr,
        )
        return 2
    results = [
        compute(companies[isin], inst.profile)
        for isin, inst in instruments.items()
        if isin in companies
    ]
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(
        "[" + ",".join(r.model_dump_json() for r in results) + "]", encoding="utf-8"
    )
    for r in results:
        pe, roe = r.get("pe_ttm"), r.get("roe")
        print(
            f"{r.name[:32]:32} P/E {pe.value if pe and pe.value is not None else 'n/a'}  ROE {roe.value if roe and roe.value is not None else 'n/a'}"
        )
    print(f"Wrote {args.json}")
    return 0


def cmd_thesis(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    instruments = load_instruments(args.instruments)
    companies = load_companies(
        instruments, args.screener, _portfolio_or_none(args.input), args.cache
    )
    try:
        llm = AnthropicLLM()
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    store = ThesisStore(args.store, {k: i.symbol for k, i in instruments.items() if i.symbol})
    failed = 0
    failed_names: list[str] = []
    all_metrics = {
        isin: compute(companies[isin], inst.profile)
        for isin, inst in instruments.items()
        if isin in companies
    }
    cohort = {m.name: from_metrics(m) for m in all_metrics.values()}
    loader = PeerLoader({} if args.no_peers else load_peer_groups(args.peers), args.cache)
    for isin, inst in instruments.items():
        if args.only and args.only.upper() not in (inst.symbol or "").upper():
            continue
        m = all_metrics.get(isin)
        if m is None:
            print(f"  - {inst.symbol or isin}: no fundamentals loaded, skipped")
            continue
        prior = store.latest(isin)
        ctx = None
        if inst.peer_group and loader.groups:
            peers = loader.peers_of(
                inst.peer_group, {inst.edgar or "", (inst.screener or "").upper()}
            )
            ctx = sector_context(inst.peer_group, m, peers, inst.profile)
            shown = (
                f"quality percentile {ctx.quality_pct:.0f}"
                if ctx.quality_pct is not None
                else ctx.note
            )
            print(f"  - {inst.symbol}: peers '{inst.peer_group}' ({ctx.peers}): {shown}")
        docs = load_documents(args.research, inst.symbol or isin)
        t, note, last = None, "", None
        for attempt in range(1, 4):  # model output is occasionally malformed; try up to 3 times
            try:
                t = thesis_analyst.run(llm, isin, m.name, inst.sector, m, prior, docs, ctx)
                note = ""
                if prior is not None and prior.inputs_digest == t.inputs_digest:
                    t = t.model_copy(update={"skeptic_counter_case": prior.skeptic_counter_case})
                elif not args.no_skeptic:
                    r = skeptic.run(llm, t, m.name, from_metrics(m) + docs, cohort)
                    case = r.counter_case + (
                        f" What would change this view: {r.would_change_my_mind}"
                        if r.would_change_my_mind
                        else ""
                    )
                    t = t.model_copy(update={"skeptic_counter_case": case})
                    note = f" skeptic {r.tool_calls} tool calls"
                break
            except LLMError as exc:
                t, last = None, exc
                if attempt < 3:
                    print(f"  - {inst.symbol}: attempt {attempt} failed ({exc}); retrying")
        if t is None:
            failed += 1
            failed_names.append(inst.symbol or isin)
            print(f"  - {inst.symbol}: FAILED after 3 attempts ({last})")
            continue
        store.save(t)
        print(
            f"  - {inst.symbol:10} docs {len(docs):3} v{t.version} {t.change_decision.value:9} {t.stance.value:12} confidence {t.confidence.value}{note}"
        )
        for r_ in t.rejected_changes:
            print(f"      rejected: {r_}")
    if failed_names:
        print(f"\n{failed} failed: {', '.join(failed_names)}. Re-run with --only <SYMBOL>.")
    return 1 if failed else 0


def cmd_advise(args: argparse.Namespace) -> int:
    import json

    from dotenv import load_dotenv

    from parakh_advisor.advice.apply import apply_advice
    from parakh_advisor.alerts.changes import load_state, save_state

    load_dotenv()
    try:
        rows = load_rows(args.input)
        resolver = MfapiResolver(args.cache) if args.online else None
        portfolio = build_portfolio(rows, fund_resolver=resolver)
        policy = load_policy(args.policy)
        instruments = load_instruments(args.instruments)
        snap = build_snapshot(
            portfolio, policy, member=args.member, acknowledged=acknowledged_flags(instruments)
        )
    except (ExportError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    failures: list[str] = []
    companies = load_companies(instruments, args.screener, portfolio, args.cache, failures=failures)
    store = ThesisStore(args.store, {k: i.symbol for k, i in instruments.items() if i.symbol})
    metrics = {
        isin: compute(companies[isin], i.profile)
        for isin, i in instruments.items()
        if isin in companies
    }
    theses = {isin: t for isin in instruments if (t := store.latest(isin))}
    state_path = Path(args.state)
    state = load_state(state_path)
    alerts, new_state = apply_advice(snap, policy, theses, metrics, instruments, state)
    alerts = collapse_baseline(alerts)
    notices = list(failures)
    fund_health = {}
    if args.online:
        from parakh_advisor.advice.funds import apply_fund_health, is_equity_fund
        from parakh_advisor.funds.health import NavSource, assess

        navs = NavSource(args.cache)
        for h in snap.holdings:
            if is_equity_fund(h) and h.scheme_code:
                fund_health[h.instrument_id] = assess(
                    h.scheme_code, h.name, h.category or "", h.plan, navs
                )
        apply_fund_health(snap, fund_health)
        from parakh_advisor.advice.funds import apply_lookthrough

        notices += apply_lookthrough(snap, args.funds)
    held = {h.instrument_id for h in snap.holdings}
    for isin in instruments:
        if isin in held and isin in companies and isin not in theses:
            sym = instruments[isin].symbol or isin
            notices.append(
                f"{sym}: fundamentals loaded but no thesis yet. "
                f"Run: uv run parakh-advisor thesis --only {sym}"
            )
    if notices:
        print("ATTENTION: some holdings could not be fully analysed:", file=sys.stderr)
        for n in notices:
            print(f"  ! {n}", file=sys.stderr)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_snapshot(snap, alerts=alerts, notices=notices), encoding="utf-8")
    Path(args.alerts).write_text(
        json.dumps([a.model_dump() for a in alerts], indent=2), encoding="utf-8"
    )
    if not args.dry_run:
        save_state(state_path, new_state)
    from parakh_advisor.notify.telegram import build_digest

    digest = build_digest(snap, alerts, str(out))
    Path(args.digest).write_text(digest, encoding="utf-8")
    if args.send:
        from parakh_advisor.notify.telegram import send
        from parakh_advisor.sources.http import SourceError

        try:
            send(digest)
            print("Digest sent to Telegram.")
        except SourceError as exc:
            print(f"warning: digest not sent ({exc}). Saved to {args.digest}", file=sys.stderr)
    print(f"Wrote {out}  ({len(alerts)} alert(s))")
    for a in alerts:
        print(f"  [{a.severity.upper():6}] {a.symbol}: {a.title}")
    for h in snap.holdings:
        if h.stance:
            print(
                f"  {h.symbol or h.name:10} {h.weight_pct:5.1f}%  {h.stance:12} {h.valuation or '-':9} -> {h.action.value if h.action else '-'}"
            )
    return 0


def cmd_fetch_docs(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv

    from parakh_advisor.research.fetch import fetch_all

    load_dotenv()
    instruments = load_instruments(args.instruments)
    if not instruments:
        print(f"No instruments in {args.instruments}", file=sys.stderr)
        return 2
    from parakh_advisor.sources.http import browser_get

    reports = fetch_all(
        instruments,
        args.research,
        args.cache,
        only=args.only,
        doc_fetch=browser_get if args.browser_headers else None,
    )
    manual = 0
    for r in reports:
        line = f"{r.symbol:<14} new {len(r.written)}, already had {r.already_had}"
        if r.to_download:
            line += f", {len(r.to_download)} to download by hand"
            manual += len(r.to_download)
        print(line)
        for n in r.notes:
            print(f"    - {n}")
    if manual:
        print(
            f"\n{manual} document(s) the exchange would not serve to a program are listed in "
            f"TO_DOWNLOAD.txt inside each stock's folder under {args.research}."
        )
    print("Next: parakh-advisor thesis, then parakh-advisor advise --online")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="parakh-advisor", description="Portfolio advisory. Advisory only."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("snapshot", help="Portfolio risk snapshot from a WealthLens export")
    p.add_argument("--input", required=True, help="WealthLens holdings JSON export")
    p.add_argument("--out", default="out/portfolio.html")
    p.add_argument("--json", help="Also write the snapshot as JSON")
    p.add_argument("--policy", default="config/policy.yaml")
    p.add_argument("--member", help="Only this member_id (default: all members combined)")
    p.add_argument("--instruments", default="config/instruments.yaml")
    p.add_argument("--online", action="store_true", help="Resolve funds via AMFI/mfapi (cached)")
    p.add_argument("--cache", default="data/cache")
    p.set_defaults(func=cmd_snapshot)
    m = sub.add_parser("metrics", help="Quality and valuation metrics from Screener exports")
    m.add_argument("--screener", default="data/inbox/screener")
    m.add_argument("--instruments", default="config/instruments.yaml")
    m.add_argument("--json", default="out/metrics.json")
    m.add_argument(
        "--input", default="data/inbox/holdings.json", help="WealthLens export (gives US prices)"
    )
    m.add_argument("--cache", default="data/cache")
    m.set_defaults(func=cmd_metrics)
    ad = sub.add_parser(
        "advise", help="Advice per holding from theses, valuation and your policy; alerts on change"
    )
    ad.add_argument("--input", required=True, help="WealthLens holdings JSON export")
    ad.add_argument("--out", default="out/advice.html")
    ad.add_argument("--alerts", default="out/alerts.json")
    ad.add_argument("--state", default="data/advice/state.json")
    ad.add_argument(
        "--funds", default="data/inbox/funds", help="Folder of fund portfolio files (xlsx/csv)"
    )
    ad.add_argument(
        "--digest", default="out/digest.txt", help="Where to write the plain-text digest"
    )
    ad.add_argument(
        "--send", action="store_true", help="Also send the digest to Telegram (needs .env keys)"
    )
    ad.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not update the saved state (alerts will repeat next run)",
    )
    ad.add_argument("--policy", default="config/policy.yaml")
    ad.add_argument("--member")
    ad.add_argument("--online", action="store_true")
    ad.add_argument("--cache", default="data/cache")
    ad.add_argument("--screener", default="data/inbox/screener")
    ad.add_argument("--instruments", default="config/instruments.yaml")
    ad.add_argument("--store", default="data/theses")
    ad.set_defaults(func=cmd_advise)
    th = sub.add_parser(
        "thesis", help="Write or refresh theses (calls the LLM; needs ANTHROPIC_API_KEY)"
    )
    th.add_argument("--screener", default="data/inbox/screener")
    th.add_argument("--instruments", default="config/instruments.yaml")
    th.add_argument("--store", default="data/theses")
    th.add_argument(
        "--research", default="data/inbox/research", help="Folder of <SYMBOL>/ documents you supply"
    )
    th.add_argument(
        "--input", default="data/inbox/holdings.json", help="WealthLens export (gives US prices)"
    )
    th.add_argument("--cache", default="data/cache")
    th.add_argument(
        "--peers", default="config/peers.yaml", help="Peer groups for sector percentiles"
    )
    th.add_argument("--no-peers", action="store_true", help="Skip sector percentiles")
    th.add_argument("--no-skeptic", action="store_true", help="Skip the Skeptic (saves LLM calls)")
    th.add_argument("--only", help="Only symbols containing this text, e.g. HDFC")
    th.set_defaults(func=cmd_thesis)
    fd = sub.add_parser(
        "fetch-docs",
        help="Download filings (EDGAR for US; Screener-listed transcripts/results for India)",
    )
    fd.add_argument("--instruments", default="config/instruments.yaml")
    fd.add_argument("--research", default="data/inbox/research")
    fd.add_argument("--cache", default="data/cache")
    fd.add_argument("--only", help="Only symbols containing this text, e.g. META")
    fd.add_argument(
        "--browser-headers",
        action="store_true",
        help="Send browser-style headers when downloading India documents from the exchange "
        "(off by default; use only if the exchange refuses the default request)",
    )
    fd.set_defaults(func=cmd_fetch_docs)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
