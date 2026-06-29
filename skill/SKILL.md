---
name: tradingagents-biga
description: 调研A股股票并生成调研报告。当用户需要对某个具体A股股票进行调研时使用此技能。输入6位股票代码如300308
version: 0.1.0
author: villain3380
metadata:
  hermes:
    tags: [a-share, stock, investment, finance, stock-analysis, report-generate, analysis]
---

# TradingAgents-BigA

## Overview

7-analyst A-share pipeline: market, sentiment, news, fundamentals, policy,
hot-money, and lockup analysts run in parallel → bull-vs-bear debate → trader
→ three-way risk debate → portfolio manager → **BUY/HOLD/SELL** signal.

**Duration:** 3–8 minutes per ticker. Research tool, not real-time trading.

## Prerequisites

Before the first run, the user must have:

1. `pip install -e .` executed in the project root.
2. LLM provider configured in `~/.tradingagents-biga/settings.json`.

If unconfigured, guide the user:

```json
{
  "default_provider": "deepseek",
  "providers": {
    "deepseek": {
      "quick_think_llm": "deepseek-chat",
      "deep_think_llm": "deepseek-reasoner",
      "api_key": "sk-your-key-here"
    }
  }
}
```

Supported providers: `openai`, `anthropic`, `deepseek`, `minimax`, `qwen`,
`glm`, `huoshan`, `xai`, `openrouter`, `ollama`.

## Entry Point

```bash
{{python}} {{project_root}}/skill/tools.py analyze --ticker 300308 --date 2026-06-29
```

Replace `{{python}}` and `{{project_root}}` with the configured values from
YAML metadata above. The script prints JSON to stdout and writes a full
Markdown report to `~/.tradingagents-biga/reports/{ticker}_{date}.md`.

## Workflow

When the user asks to analyse an A-share stock:

1. **Resolve ticker.** Company name → 6-digit numeric code. Do NOT guess —
   ask the user if ambiguous (e.g. "中际旭创" → "300308").

2. **Confirm date.** Use today if unspecified. The analysis is based on data
   available up to that date.

3. **Run `tools.py analyze`.** Warn the user this takes 3–8 minutes. Execute
   the command and show progress lines from stderr.

4. **Read the report.** Parse the JSON result for `report_path`, then read
   the Markdown file at that path with the Read tool.

5. **Summarise for the user:**
   - Final signal (BUY/HOLD/SELL) and conviction
   - 1–2 key sentences per analyst
   - Bull vs bear clash highlights
   - Risk assessment summary
   - Report file path for reference

## Commands

```bash
# Full analysis (3-8 min)
python <skill_dir>/tools.py analyze --ticker 300308 --date 2026-06-29

# List analyst roles
python <skill_dir>/tools.py list-analysts

# List configured LLM providers (no keys exposed)
python <skill_dir>/tools.py list-providers
```

## Notes

- Read-only: queries public financial data, never places trades.
- Reports saved to `~/.tradingagents-biga/reports/`. Re-running same
  ticker+date overwrites the previous file.
- `ModuleNotFoundError` → user hasn't run `pip install -e .` yet.
