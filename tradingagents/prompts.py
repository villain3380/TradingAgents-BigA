"""Prompt cache — loads agent system prompts from ``prompts/*.md`` on first use,
falling back to the built-in default if a file is missing or unreadable.

Usage::

    from tradingagents.prompts import get_prompt
    system_message = get_prompt("market_analyst")

The ``prompts/`` directory sits at the project root. If a user edits a file
during a running session, the next call to ``get_prompt`` returns the updated
content (no restart needed).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PROMPTS_DIR = _PROJECT_ROOT / "prompts"

# Built-in fallbacks — mirrored from the initial prompts/*.md files.
# When a .md file is deleted/corrupt, we use this so the pipeline never breaks.
_FALLBACKS: dict[str, str] = {}


def _prompt_path(name: str) -> Path:
    return _PROMPTS_DIR / f"{name}.md"


def _load_manifest() -> list[dict]:
    """Read manifest.json — used by the frontend to discover available prompts."""
    try:
        data = json.loads((_PROMPTS_DIR / "manifest.json").read_text(encoding="utf-8"))
        return data.get("prompts", [])
    except Exception:
        return []


def list_prompts() -> list[dict]:
    """Return the manifest entries (name, label, icon, variables, description)."""
    return _load_manifest()


def get_default_prompt(name: str) -> str:
    """Return the hardcoded default for *name* (empty string if unknown)."""
    return _FALLBACKS.get(name, "")


def get_prompt(name: str) -> str:
    """Load the prompt for *name* from ``prompts/<name>.md``.

    Falls back to the built-in default (registered via ``_register_fallback``) if
    the file is missing or unreadable; never raises.
    """
    path = _prompt_path(name)
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return _FALLBACKS.get(name, "")


def save_prompt(name: str, content: str) -> None:
    """Overwrite ``prompts/<name>.md`` with *content* (atomic write).

    Raises ``ValueError`` if *name* is not in the manifest.
    """
    manifest_names = {e["name"] for e in _load_manifest()}
    if name not in manifest_names:
        raise ValueError(f"Unknown prompt name: {name}")
    path = _prompt_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def reset_prompt(name: str) -> None:
    """Restore the built-in default for *name* (overwrites the .md file)."""
    default = _FALLBACKS.get(name, "")
    if default:
        save_prompt(name, default)


# ── register default prompts (mirrored from prompt/*.md) ──
# Analyst system messages (no variables)
_FALLBACKS["market_analyst"] = (
    "你是一位专注于 A 股市场的技术分析师。你的任务是从以下技术指标中选择最多 **8** 个…"
)

_FALLBACKS["social_media_analyst"] = (
    "你是一位专注于 A 股市场的市场情绪分析师…"
)

_FALLBACKS["news_analyst"] = (
    "你是一位专注于 A 股市场的新闻与政策分析师…"
)

_FALLBACKS["fundamentals_analyst"] = (
    "你是一位专注于 A 股市场的基本面分析师…"
)

_FALLBACKS["policy_analyst"] = (
    "你是一位专注于 A 股市场的政策分析师…"
)

_FALLBACKS["hot_money_tracker"] = (
    "你是一位专注于 A 股市场的游资与资金流向追踪分析师…"
)

_FALLBACKS["lockup_watcher"] = (
    "你是一位专注于 A 股市场的解禁与减持监控分析师…"
)

# Template prompts (with variables)
_FALLBACKS["bull_researcher"] = (
    "You are a Bull Analyst advocating for investing in this A-share stock…"
)

_FALLBACKS["bear_researcher"] = (
    "You are a Bear Analyst making the case against investing in this A-share stock…"
)

_FALLBACKS["aggressive_debator"] = (
    "As the Aggressive Risk Analyst evaluating an A-share stock…"
)

_FALLBACKS["conservative_debator"] = (
    "As the Conservative Risk Analyst evaluating an A-share stock…"
)

_FALLBACKS["neutral_debator"] = (
    "As the Neutral Risk Analyst evaluating an A-share stock…"
)

_FALLBACKS["research_manager"] = (
    "As the Research Manager and debate facilitator…"
)

_FALLBACKS["trader"] = (
    "You are a trading agent specialising in A-share stocks…"
)

_FALLBACKS["portfolio_manager"] = (
    "As the Portfolio Manager, synthesize the risk analysts' debate…"
)
