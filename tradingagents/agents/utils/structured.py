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

# Model name substrings that indicate a "thinking"/reasoning model. These
# models reject tool_choice (function-calling), so structured output via
# function_calling fails with HTTP 400 ("Thinking mode does not support this
# tool_choice"). Skip the structured attempt for them and go straight to
# free-text — same end result as the runtime fallback, but without the failed
# API call + noisy error log on every run.
_THINKING_MARKERS = ("reasoner", "think", "latest", "o1", "o3", "r1")


def _is_thinking_model(llm: Any) -> bool:
    """Heuristic: does this LLM look like a thinking/reasoning model?"""
    name = ""
    for attr in ("model_name", "model", "deployment_name"):
        v = getattr(llm, attr, None)
        if isinstance(v, str) and v:
            name = v
            break
    if not name:
        return False
    lname = name.lower()
    return any(m in lname for m in _THINKING_MARKERS)


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Optional[Any]:
    """Return ``llm.with_structured_output(schema)`` or ``None`` if unsupported.

    Returns None (free-text) when:
    - the provider doesn't support with_structured_output (NotImplementedError)
    - the model is a thinking/reasoning model (rejects tool_choice at the API)

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
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            return render(result)
        except Exception as exc:
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )

    response = plain_llm.invoke(prompt)
    return response.content
