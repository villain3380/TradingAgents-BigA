"""Analyst registry — single source of truth for pluggable analysts.

All analyst metadata (key, display label, icon, state report field, factory)
lives here. Consumers (graph setup, quality gate, web progress panel, runner)
read from this registry instead of hardcoding the 7 analysts, so adding or
removing an analyst only requires editing this file.

Pluggability contract:
    Add an analyst  = write a ``create_xxx`` factory + append one AnalystSpec.
    Remove one      = delete its AnalystSpec line (or just deselect it).
    setup.py / quality_gate.py / web/* need NO changes.
"""

from dataclasses import dataclass
from typing import Callable

from .fundamentals_analyst import create_fundamentals_analyst
from .hot_money_tracker import create_hot_money_tracker
from .lockup_watcher import create_lockup_watcher
from .market_analyst import create_market_analyst
from .news_analyst import create_news_analyst
from .policy_analyst import create_policy_analyst
from .social_media_analyst import create_social_media_analyst


@dataclass(frozen=True)
class AnalystSpec:
    """Metadata + factory for one analyst role.

    Attributes:
        key: stable identifier used in ``selected_analysts`` and node names.
        label: Chinese display name (quality gate prompt + web UI).
        icon: emoji for the web progress panel.
        report_field: AgentState field the analyst writes its report into.
        create: factory ``create_xxx(llm) -> node_fn``.
    """

    key: str
    label: str
    icon: str
    report_field: str
    create: Callable


# Ordered list — order doubles as the default display/iteration order.
ANALYST_REGISTRY: list[AnalystSpec] = [
    AnalystSpec("market", "技术分析师", "📊", "market_report", create_market_analyst),
    AnalystSpec("social", "情绪分析师", "💬", "sentiment_report", create_social_media_analyst),
    AnalystSpec("news", "新闻分析师", "📰", "news_report", create_news_analyst),
    AnalystSpec("fundamentals", "基本面分析师", "📋", "fundamentals_report", create_fundamentals_analyst),
    AnalystSpec("policy", "政策分析师", "🏛️", "policy_report", create_policy_analyst),
    AnalystSpec("hot_money", "游资追踪师", "🔥", "hot_money_report", create_hot_money_tracker),
    AnalystSpec("lockup", "解禁监控师", "🔒", "lockup_report", create_lockup_watcher),
]

ANALYST_BY_KEY: dict[str, AnalystSpec] = {s.key: s for s in ANALYST_REGISTRY}
DEFAULT_SELECTED: list[str] = [s.key for s in ANALYST_REGISTRY]


def resolve_selected(selected: list[str] | None) -> list[AnalystSpec]:
    """Map a selection of keys to AnalystSpecs, preserving registry order.

    Unknown keys are silently dropped. ``None`` or empty → all analysts.
    """
    if not selected:
        return list(ANALYST_REGISTRY)
    selected_set = set(selected)
    return [s for s in ANALYST_REGISTRY if s.key in selected_set]


def analyst_report_keys(selected: list[str] | None = None) -> list[str]:
    """Return the report_field names for the given selection (or all)."""
    return [s.report_field for s in resolve_selected(selected)]
