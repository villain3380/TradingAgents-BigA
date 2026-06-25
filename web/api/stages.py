"""Stage-completion detection for the SSE API.

Mirrors the logic in ``web/runner.py:_detect_completed_stages`` but returns a
list of newly-completed stage events (instead of mutating a ProgressTracker),
so the FastAPI SSE layer can forward them as ``stage_done`` events.

In ``stream_mode="updates"`` each chunk is ``{node_name: state_delta_dict}``:
the node that just ran mapped to the fields it wrote. We inspect the delta to
see which analyst report / downstream artifact appeared.
"""

from __future__ import annotations

import re
from typing import Any

from tradingagents.agents.analysts.registry import resolve_selected


def _strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


# Downstream (non-analyst) stage detection: field -> (stage_id, display_name).
_DOWNSTREAM_FIELDS = [
    ("data_quality_summary", "quality_gate", "质量门控"),
    ("trader_investment_plan", "trader", "交易决策"),
    ("final_trade_decision", "pm", "最终决策"),
]


def detect_stage_events(
    delta: dict[str, Any],
    completed: set[str],
    selected_analysts: list[str] | None,
    ticker: str,
) -> list[dict]:
    """Return stage-done events for fields that just appeared in ``delta``.

    Args:
        delta: the state delta from a ``stream_mode="updates"`` chunk. May be
            the raw delta dict, or ``{node_name: delta}`` — flattened here.
        completed: mutable set of stage ids already reported; updated in place
            so each stage fires exactly once.
        selected_analysts: keys of active analysts (for report-field mapping).
        ticker: for report normalization (kept for parity with runner.py).

    Returns:
        list of ``{"agent_id"|"stage", ...}`` dicts to emit as stage_done.
    """
    events: list[dict] = []

    # Flatten {node_name: delta} into a single delta view of present fields.
    flat: dict[str, Any] = {}
    if delta and all(isinstance(v, dict) for v in delta.values()):
        for v in delta.values():
            flat.update(v)
    else:
        flat = dict(delta or {})

    # Analyst reports.
    for spec in resolve_selected(selected_analysts):
        content = flat.get(spec.report_field, "")
        if content and spec.key not in completed:
            completed.add(spec.key)
            events.append({"agent_id": spec.key, "report": _strip_think_tags(str(content))})

    # Debate judge decision (nested).
    debate = flat.get("investment_debate_state")
    if isinstance(debate, dict) and debate.get("judge_decision") and "debate" not in completed:
        completed.add("debate")
        events.append({"stage": "debate", "name": "多空辩论"})

    # Risk judge decision (nested).
    risk = flat.get("risk_debate_state")
    if isinstance(risk, dict) and risk.get("judge_decision") and "risk" not in completed:
        completed.add("risk")
        events.append({"stage": "risk", "name": "风控评估"})

    # Simple downstream scalar fields.
    for field, stage_id, name in _DOWNSTREAM_FIELDS:
        if flat.get(field) and stage_id not in completed:
            completed.add(stage_id)
            events.append({"stage": stage_id, "name": name})

    return events
