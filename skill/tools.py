#!/usr/bin/env python3
"""CLI entry point called by the Hermes skill.  Usage::

    python tools.py analyze --ticker 000001 --date 2026-06-29
    python tools.py list-analysts
    python tools.py list-providers

All sub-commands write JSON to stdout.  Stderr carries progress/error lines so
Hermes can see what's happening during long ``analyze`` runs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _progress(msg: str) -> None:
    print(f"[tradingagents] {msg}", file=sys.stderr, flush=True)


# ── sub-commands ──────────────────────────────────────────────────────────────

def cmd_list_analysts() -> int:
    from tradingagents.agents.analysts.registry import ANALYST_REGISTRY
    result = [
        {"key": s.key, "label": s.label, "icon": s.icon, "report_field": s.report_field}
        for s in ANALYST_REGISTRY
    ]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_list_providers() -> int:
    from tradingagents.settings import load_settings
    settings = load_settings()
    providers = settings.get("providers", {})
    result = []
    for key, cfg in providers.items():
        result.append({
            "key": key,
            "quick_think_llm": cfg.get("quick_think_llm", ""),
            "deep_think_llm": cfg.get("deep_think_llm", ""),
            "has_key": bool(cfg.get("api_key")),
        })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_analyze(ticker: str, date: str) -> int:
    import asyncio
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.agents.utils.sft_recorder import start_sft_recording, stop_sft_recording

    _progress(f"analyze start: ticker={ticker} date={date}")
    t0 = time.time()

    async def _run():
        graph = TradingAgentsGraph(debug=False)
        try:
            init_state, args, _ = graph.prepare_graph_run(ticker, date)
            _progress("graph prepared; invoking pipeline ...")
            start_sft_recording(ticker, str(date))
            # Use ainvoke — analyst nodes are async def
            final_state = await graph.graph.ainvoke(init_state, **args)
            signal = graph.finalize_graph_run(ticker, date, final_state)
            return final_state, signal
        finally:
            stop_sft_recording()
            graph.close_graph_run()

    final_state, signal = asyncio.run(_run())

    # Auto-save Markdown
    from web.pdf_export import generate_markdown
    md = generate_markdown(final_state, ticker, date, signal)
    reports_dir = Path.home() / ".tradingagents-biga" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    md_path = reports_dir / f"{ticker}_{date}.md"
    md_path.write_text(md, encoding="utf-8")

    elapsed = round(time.time() - t0, 1)
    result = {
        "ticker": ticker,
        "date": date,
        "signal": signal,
        "report_path": str(md_path),
        "elapsed_seconds": elapsed,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    _progress(f"done: {elapsed}s signal={signal}")
    return 0


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="tradingagents-skill")
    sub = parser.add_subparsers(dest="cmd")

    analyze = sub.add_parser("analyze")
    analyze.add_argument("--ticker", required=True)
    analyze.add_argument("--date", required=True)

    sub.add_parser("list-analysts")
    sub.add_parser("list-providers")

    args = parser.parse_args()

    if args.cmd == "list-analysts":
        sys.exit(cmd_list_analysts())
    elif args.cmd == "list-providers":
        sys.exit(cmd_list_providers())
    elif args.cmd == "analyze":
        sys.exit(cmd_analyze(args.ticker, args.date))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
