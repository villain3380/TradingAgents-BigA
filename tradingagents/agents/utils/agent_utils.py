from langchain_core.messages import HumanMessage, RemoveMessage, ToolMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)
from tradingagents.agents.utils.signal_data_tools import (
    get_profit_forecast,
    get_hot_stocks,
    get_northbound_flow,
    get_concept_blocks,
    get_fund_flow,
    get_dragon_tiger_board,
    get_lockup_expiry,
    get_industry_comparison,
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )


def _extract_text_delta(content) -> str:
    """Extract the text increment from a streamed chunk's content.

    ``chain.stream()`` yields ``AIMessageChunk`` whose ``content`` is a ``str``
    for Chat Completions providers (GLM/DeepSeek/Qwen/...) but may be a
    ``list[dict]`` of typed blocks (e.g. ``{"type":"text","text":...}``) under
    OpenAI's Responses API. This normalises both to a plain text delta so the
    streaming event carries clean text for the frontend.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return ""


def _resolve_agent_id() -> str | None:
    """Identify which analyst this loop is running inside, for streaming events.

    Uses LangGraph's per-node metadata: each node executes with
    ``config["metadata"]["langgraph_node"]`` set to its node name (e.g.
    ``"market_analyst"``). We strip the ``_analyst`` suffix and confirm the key
    exists in the registry. Returns ``None`` outside a graph context (unit
    tests, direct calls) so streaming is silently skipped — safe degradation.
    """
    try:
        from langgraph.config import get_config
        node = get_config().get("metadata", {}).get("langgraph_node", "")
        key = node.removesuffix("_analyst")
        from tradingagents.agents.analysts.registry import ANALYST_BY_KEY
        return key if key in ANALYST_BY_KEY else None
    except Exception:
        return None


def _get_stream_writer():
    """Return a LangGraph custom-stream writer, or a no-op callable.

    ``get_stream_writer()`` only works inside a graph run with a streaming
    consumer; outside that context it raises. We fall back to a no-op so
    ``run_react_loop`` stays callable in unit tests and the Streamlit path
    (which doesn't consume custom events).
    """
    try:
        from langgraph.config import get_stream_writer
        return get_stream_writer()
    except Exception:
        return lambda _data: None


async def stream_invoke(llm, prompt, agent_id: str) -> str:
    """Stream a free-text LLM call and forward tokens to the SSE frontend.

    Used by the downstream nodes (quality gate, bull/bear researchers, risk
    debators) that do a single ``llm.invoke(prompt)`` and return the text.
    This wraps it with ``llm.astream`` so each token is forwarded as a custom
    event carrying ``agent_id`` (e.g. "bull", "quality_gate"), letting the
    frontend show the debate/risk stages streaming live instead of blocking.

    Returns the full concatenated content — drop-in replacement for
    ``llm.invoke(prompt).content``. Outside a streaming graph context the
    writer is a no-op, so the Streamlit path is unaffected.
    """
    writer = _get_stream_writer()
    parts: list[str] = []
    async for chunk in llm.astream(prompt):
        text = _extract_text_delta(chunk.content)
        if text:
            parts.append(text)
            if agent_id:
                writer({"agent_id": agent_id, "type": "token", "text": text})
    content = "".join(parts)
    if agent_id:
        writer({"agent_id": agent_id, "type": "report_done"})
    return content


async def run_react_loop(chain, tools, initial_message, max_iterations: int = 10) -> str:
    """Self-contained ReAct tool-calling loop that stays inside one graph node.

    Runs ``chain`` (a ``prompt | llm.bind_tools(tools)``) against a *local*
    message list, executing any tool calls inline until the model stops
    requesting tools (or ``max_iterations`` is hit). The report string is
    returned; the local messages are discarded and never written back to
    ``state["messages"]``.

    This is what lets analysts run in parallel: each analyst's tool-call
    history is isolated to a local list, so concurrent analysts don't pollute
    the shared ``messages`` channel. It also removes the need for the old
    per-analyst ``ToolNode`` + conditional-edge + ``Msg Clear`` graph machinery.

    Streaming: the LLM is consumed with ``chain.astream()`` so each text token
    is forwarded to the graph's custom stream (via ``get_stream_writer``) as an
    ``analyst_event`` carrying the ``agent_id``. The frontend SSE layer turns
    these into per-card token updates. When no streaming consumer is attached
    (Streamlit path, unit tests) the writer is a no-op and behaviour is
    identical to the old ``chain.invoke`` version. The return value (full
    report string) is unchanged either way.

    Async: nodes are ``async def`` so the Web API's ``graph.astream`` runs
    analysts concurrently in one event loop. Sync tool calls are offloaded via
    ``asyncio.to_thread`` so they don't block the loop.
    """
    import asyncio

    local_messages = [initial_message]
    tool_map = {t.name: t for t in tools}
    agent_id = _resolve_agent_id()
    writer = _get_stream_writer()
    result = None

    def _emit(data: dict) -> None:
        if agent_id is not None:
            writer({**data, "agent_id": agent_id})

    for iteration in range(max_iterations):
        collected = None  # AIMessageChunk accumulator
        async for chunk in chain.astream(local_messages):
            # Text token → emit a streaming event.
            text = _extract_text_delta(chunk.content)
            if text:
                _emit({"type": "token", "text": text, "iter": iteration})
            # Tool-call fragments → accumulate only; emit the name once known.
            if chunk.tool_call_chunks:
                names = [c.get("name") for c in chunk.tool_call_chunks if c.get("name")]
                if names:
                    _emit({"type": "tool_call", "names": names, "iter": iteration})
            collected = chunk if collected is None else collected + chunk

        if collected is None:
            break
        result = collected  # accumulated: content joined, tool_calls merged

        # No tool calls → the model produced its final report.
        if not result.tool_calls:
            _emit({"type": "report_done", "iter": iteration})
            return _extract_text_delta(result.content) or result.content

        # Tool calls → execute them, emit start/end events, continue the loop.
        local_messages.append(result)
        import re
        for tc in result.tool_calls:
            _emit({"type": "tool_start", "tool": tc["name"], "iter": iteration})
            output = await asyncio.to_thread(tool_map[tc["name"]].invoke, tc["args"])
            # Extract source URLs from the tool output (get_news returns
            # "Link: <url>" lines) so the frontend can show provenance.
            sources = re.findall(r"Link:\s*(\S+)", str(output))[:5]
            _emit({"type": "tool_end", "tool": tc["name"], "iter": iteration,
                   "sources": sources})
            local_messages.append(
                ToolMessage(content=str(output), tool_call_id=tc["id"])
            )

    return _extract_text_delta(getattr(result, "content", "")) or "分析未完成（达到最大迭代次数）"

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
