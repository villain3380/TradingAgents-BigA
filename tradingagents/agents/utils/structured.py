"""Shared helpers for invoking an agent with structured output and a graceful fallback.

The Portfolio Manager, Trader, and Research Manager all follow the same
canonical pattern:

1. At agent creation, wrap the LLM with ``with_structured_output(Schema)``
   so the model returns a typed Pydantic instance. If the provider does
   not support structured output (rare; mostly older Ollama models), the
   wrap is skipped and the agent uses free-text generation instead.
2. At invocation, run the structured call and render the result back to
   markdown. If the structured call itself fails for any reason
   (malformed JSON from a weak model, transient provider issue), fall
   back to a plain ``llm.invoke`` so the pipeline never blocks.

Centralising the pattern here keeps the agent factories small and ensures
all three agents log the same warnings when fallback fires.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Reasoning/thinking models reject tool_choice (function-calling), so structured
# output via function_calling fails with HTTP 400 ("Thinking mode does not
# support this tool_choice"). For these models we skip the structured attempt
# and go straight to free-text — same end result as the runtime fallback, but
# without the failed API call + noisy error log on every run.
#
# Detection is intentionally conservative. A previous version matched broad
# substrings ("latest", "think") which mis-flagged ordinary models like
# ``glm-latest`` as reasoning models, silently disabling structured output for
# the default config. We now prefer an explicit config list and only fall back
# to high-confidence name patterns. Provider-layer guards (e.g. DeepSeek's
# with_structured_output raising NotImplementedError for deepseek-reasoner)
# remain the last line of defense.
#
# Pattern shapes:
# - Substring: ``reasoner`` / ``deepseek-r`` catch the named reasoning variants.
# - Prefix: OpenAI's o-series is named ``o1``, ``o1-mini``, ``o3``, ... — they
#   start with ``o`` + digit, so a prefix check avoids both false-positives
#   (``foo1``) and false-negatives (bare ``o1`` with no separator).
# - Anchored ``-r1`` / ``r1-``: catches ``xxx-r1`` / ``r1-xxx`` without
#   matching ``r1`` buried inside another token.
_REASONING_SUBSTRINGS = ("reasoner", "deepseek-r")
_REASONING_PREFIXES = ("o1", "o3", "o4")  # OpenAI o-series reasoning models
_REASONING_ANCHORED = ("-r1", "r1-")      # r1 family, separator on at least one side


def _resolve_model_name(llm: Any) -> str:
    """Best-effort model name extraction across LangChain chat-model variants."""
    for attr in ("model_name", "model", "deployment_name"):
        v = getattr(llm, attr, None)
        if isinstance(v, str) and v:
            return v
    return ""


def _is_thinking_model(llm: Any) -> bool:
    """Decide whether ``llm`` is a reasoning/thinking model.

    Priority:

    1. Explicit config: ``thinking_models`` (force-treat as reasoning) and
       ``non_thinking_models`` (force-treat as NOT reasoning). The latter lets
       users override a heuristic miss. Both are case-insensitive exact matches.
    2. Conservative name-pattern heuristic (``_REASONING_PATTERNS``).

    Returns False when the model name can't be determined — the provider-layer
    NotImplementedError guard and the runtime 400 fallback still apply.
    """
    name = _resolve_model_name(llm)
    if not name:
        return False
    lname = name.lower()

    try:
        from tradingagents.dataflows.config import get_config

        cfg = get_config() or {}
    except Exception:  # pragma: no cover - config must always be available
        cfg = {}

    forced = cfg.get("thinking_models")
    if isinstance(forced, list) and lname in [str(m).lower() for m in forced]:
        return True
    excluded = cfg.get("non_thinking_models")
    if isinstance(excluded, list) and lname in [str(m).lower() for m in excluded]:
        return False

    if any(s in lname for s in _REASONING_SUBSTRINGS):
        return True
    if any(lname.startswith(p) for p in _REASONING_PREFIXES):
        return True
    return any(p in lname for p in _REASONING_ANCHORED)


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Optional[Any]:
    """Return ``llm.with_structured_output(schema)`` or ``None`` if unsupported.

    Returns None (free-text) when:
    - the model is a thinking/reasoning model (rejects tool_choice at the API),
      as decided by ``_is_thinking_model`` (explicit config first, then a
      conservative name heuristic)
    - the provider doesn't support with_structured_output (NotImplementedError)

    Logs a warning when binding fails so the user understands the agent will
    use free-text generation. For thinking models, logs at INFO since it's an
    expected, non-erroneous degradation.
    """
    if _is_thinking_model(llm):
        logger.info(
            "%s: thinking/reasoning model detected — skipping structured output "
            "(tool_choice unsupported), using free-text generation",
            agent_name,
        )
        return None
    try:
        return llm.with_structured_output(schema)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning(
            "%s: provider does not support with_structured_output (%s); "
            "falling back to free-text generation",
            agent_name, exc,
        )
        return None


def invoke_structured_or_freetext(
    structured_llm: Optional[Any],
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
) -> str:
    """Run the structured call and render to markdown; fall back to free-text on any failure.

    ``prompt`` is whatever the underlying LLM accepts (a string for chat
    invocations, a list of message dicts for chat models that take that
    shape). The same value is forwarded to the free-text path so the
    fallback sees the same input the structured call did.
    """
    result: str
    if structured_llm is not None:
        try:
            obj = structured_llm.invoke(prompt)
            result = render(obj)
            _record_structured(agent_name, prompt, result)
            return result
        except Exception as exc:
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )

    response = plain_llm.invoke(prompt)
    result = response.content
    _record_structured(agent_name, prompt, result)
    return result


# ── SFT recording for structured-output agents ────────────────────────────

_STRUCTURED_ROLES: dict[str, str] = {
    "Research Manager": "研究主管",
    "Trader": "交易员",
    "Portfolio Manager": "投资组合经理",
}


def _record_structured(agent_name: str, prompt, result: str) -> None:
    """Record a structured-output agent conversation for SFT.

    *prompt* may be a plain string (Research Manager, Portfolio Manager) or a
    list of ``{"role": …, "content": …}`` dicts (Trader).  *agent_name* is the
    human-readable role label (e.g. ``"Trader"``).
    """
    if agent_name not in _STRUCTURED_ROLES:
        return

    from tradingagents.agents.utils.sft_recorder import get_sft_recorder
    recorder = get_sft_recorder()
    if recorder is None:
        return

    agent_role = _STRUCTURED_ROLES[agent_name]
    agent_id = agent_name.lower().replace(" ", "_")

    # Build messages depending on prompt type.
    messages: list[dict]
    if isinstance(prompt, list):
        # Trader: prompt is already [{"role":"system",…}, {"role":"user",…}]
        messages = [dict(m) for m in prompt]  # shallow copy
        messages.append({"role": "assistant", "content": result})
    else:
        messages = [
            {"role": "system", "content": f"你是{agent_role}。"},
            {"role": "user", "content": str(prompt)},
            {"role": "assistant", "content": result},
        ]

    recorder.record(agent_id=agent_id, agent_role=agent_role, tools=[], messages=messages)
