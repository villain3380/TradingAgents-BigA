from langchain_core.messages import ToolMessage

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


def _get_react_timeout() -> "float | None":
    """Per-analyst ReAct loop timeout in seconds, from config (None = off).

    Bounds a single analyst so a slow or stuck one degrades to a failure
    report instead of hanging the Quality Gate barrier — analysts fan out in
    parallel but fan-in is a barrier, so one slow node blocks them all.
    """
    try:
        from tradingagents.dataflows.config import get_config

        v = (get_config() or {}).get("react_loop_timeout")
        return float(v) if v else None
    except Exception:
        return None


async def _invoke_tool_safe(tool_map, tc, iteration, _emit, cache=None):
    """Run one tool call with full error recovery.

    Returns ``(output, sources)``. On any failure — a hallucinated tool name,
    malformed args, or a tool-execution exception — returns an error string
    and empty sources so the LLM sees the error as a ``ToolMessage`` and can
    self-correct, instead of the node crashing and hanging the barrier.

    *cache* is a per-run (dict or None) keyed by ``(tool_name, sorted args
    items)``. When the same tool is called with identical arguments by
    multiple analysts (e.g. five analysts calling get_news for the same
    ticker), the first call fetches the data; subsequent calls return the
    cached result instantly — no duplicate HTTP request, no duplicate
    source URLs in the right rail.
    """
    import asyncio
    import re

    tool_name = tc.get("name", "?")
    tool = tool_map.get(tool_name)

    # P10: args completeness check. Streaming shard merges (national
    # OpenAI-compat providers) can leave tc["args"] as None or a half-cut
    # JSON string instead of a dict. Reject these BEFORE invoking the tool —
    # a half-cut arg dict would KeyError/TypeError inside the tool and waste
    # a turn. We only reject on a clear TYPE mismatch (non-dict); an empty
    # dict {} is a legal "no-args" call and must NOT be rejected, otherwise
    # we'd loop forever asking the LLM to resend a valid call. Repeated
    # resends are still bounded by max_iterations, so no infinite loop.
    args = tc.get("args")
    if not isinstance(args, dict):
        _emit({"type": "tool_end", "tool": tool_name, "iter": iteration, "sources": []})
        return (
            f"Error: tool '{tool_name}' arguments were malformed "
            f"(got {type(args).__name__}, expected a JSON object). "
            f"Please re-issue the tool call with valid JSON arguments."
        ), []

    if tool is None:
        _emit({"type": "tool_end", "tool": tool_name, "iter": iteration, "sources": []})
        available = ", ".join(tool_map.keys())
        return (
            f"Error: tool '{tool_name}' is not available. "
            f"Available tools: {available}. Call one of those instead."
        ), []

    # Per-run cache: key = (tool_name, frozendict-like tuple of sorted args).
    # When 5 analysts call get_news("300308", "2026-06-20", ...) only the
    # first one hits the API; the other 4 return the cached result. Cache is
    # a plain dict — concurrent calls from parallel analysts may race but
    # the worst case is one extra call, still far better than 5×.
    cache_key = None
    if cache is not None:
        try:
            cache_key = (tool_name, tuple(sorted(args.items())))
            cached = cache.get(cache_key)
            if cached is not None:
                _emit({"type": "tool_end", "tool": tool_name, "iter": iteration,
                       "sources": cached[1]})
                return cached
        except TypeError:
            pass  # unhashable arg value — can't cache, proceed normally

    try:
        output = await asyncio.to_thread(tool.invoke, args)
    except Exception as exc:
        # Malformed args (streaming shard merge), provider error, etc.
        _emit({"type": "tool_end", "tool": tool_name, "iter": iteration, "sources": []})
        return f"Error calling tool '{tool_name}': {exc}", []

    sources = re.findall(r"Link:\s*(\S+)", str(output))[:5]
    _emit({"type": "tool_end", "tool": tool_name, "iter": iteration, "sources": sources})
    result = (output, sources)
    if cache is not None and cache_key is not None:
        cache[cache_key] = result
    return result


def _get_prompt_budget() -> int:
    """Max tokens a single downstream prompt may occupy before compression.

    From config ``prompt_token_budget`` (default 100000). P8: prompts are left
    untouched under the budget — no truncation, no summary, so debate/report
    quality is preserved. Only when a prompt exceeds the budget do we ask the
    LLM to compress it (one extra call) so the run doesn't blow the model's
    context window and crash mid-debate.
    """
    try:
        from tradingagents.dataflows.config import get_config

        v = (get_config() or {}).get("prompt_token_budget")
        return int(v) if v else 100_000
    except Exception:
        return 100_000


def _estimate_tokens(text: str) -> int:
    """Rough token count for budget gating.

    Uses tiktoken's cl100k encoding as a provider-agnostic estimate. The
    exact tokenizer differs per provider (GLM/Qwen/DeepSeek each have their
    own), but this is only used to detect a prompt that *grossly* exceeds the
    budget — a ~10% estimation error is fine for that go/no-go decision.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(str(text)))
    except Exception:
        # Fallback: ~4 chars/token for CJK-heavy text. Less accurate but
        # keeps the budget guard working even if tiktoken data is missing.
        return len(str(text)) // 4


async def _compress_prompt(llm, prompt: str, budget: int) -> str:
    """Compress an over-budget prompt via one LLM call, preserving facts.

    The compression prompt instructs the model to keep all specific numbers,
    dates, tickers, and conclusions — only redundant prose and verbose
    formatting are dropped. The compressed text targets ~60% of the budget so
    there's headroom for the model's own response. On any failure the original
    prompt is returned unchanged (better to risk a long call than to lose the
    analyst data entirely).

    Async + ``asyncio.to_thread`` so the synchronous compression call doesn't
    block the event loop while analysts run concurrently.
    """
    import asyncio

    target = int(budget * 0.6)
    compress_instruction = (
        "The following content is too long for the model context window. "
        "Compress it to roughly equivalent information density at a target of "
        f"~{target} tokens. You MUST preserve: every specific number, price, "
        "percentage, date, ticker code, and named entity; every concrete "
        "conclusion or signal. You MAY cut: redundant phrasing, verbose "
        "formatting, repeated caveats, and non-essential commentary. Do not "
        "add new information. Output only the compressed content."
    )
    try:
        resp = await asyncio.to_thread(
            llm.invoke,
            [("system", compress_instruction), ("human", prompt)],
        )
        compressed = _extract_text_delta(getattr(resp, "content", "")) or str(getattr(resp, "content", ""))
        if compressed and _estimate_tokens(compressed) < _estimate_tokens(prompt):
            return compressed
        return prompt  # compression didn't help; keep original
    except Exception:
        return prompt


async def stream_invoke(llm, prompt, agent_id: str) -> str:
    """Stream a free-text LLM call and forward tokens to the SSE frontend.

    Used by the downstream nodes (quality gate, bull/bear researchers, risk
    debators) that do a single ``llm.invoke(prompt)`` and return the text.
    This wraps it with ``llm.astream`` so each token is forwarded as a custom
    event carrying ``agent_id`` (e.g. "bull", "quality_gate"), letting the
    frontend show the debate/risk stages streaming live instead of blocking.

    P8 budget guard: if *prompt* exceeds the configured token budget
    (default 100k), it is compressed once via ``llm.invoke`` before streaming.
    Under the budget the prompt is passed through untouched — no truncation,
    no information loss — so debate and report quality is preserved.

    Returns the full concatenated content — drop-in replacement for
    ``llm.invoke(prompt).content``. Outside a streaming graph context the
    writer is a no-op, so the Streamlit path is unaffected.
    """
    budget = _get_prompt_budget()
    prompt_tokens = _estimate_tokens(prompt)
    if prompt_tokens > budget:
        original_tokens = prompt_tokens
        prompt = await _compress_prompt(llm, prompt, budget)
        writer = _get_stream_writer()
        if agent_id:
            writer({"agent_id": agent_id, "type": "token",
                    "text": f"[prompt compressed: {original_tokens}→{_estimate_tokens(prompt)} tokens to fit {budget} budget]\n"})

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

    # SFT recording: single-turn, no tools.
    _record_downstream(agent_id, prompt, content)
    return content


async def run_react_loop(chain, tools, initial_message, max_iterations: int = 10,
                        system_prompt_text: str = "") -> str:
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

    SFT recording: when *system_prompt_text* is provided and an SFT recorder
    is active, the complete conversation (system → user → assistant/tool_calls
    → tool_result → ... → assistant/final) is captured after the loop and
    written to the session's JSONL file at flush time.
    """
    import asyncio

    local_messages = [initial_message]
    tool_map = {t.name: t for t in tools}
    tool_cache: dict = {}  # per-run: (tool_name, sorted args) → (output, sources)
    agent_id = _resolve_agent_id()
    writer = _get_stream_writer()
    result = None

    def _emit(data: dict) -> None:
        if agent_id is not None:
            writer({**data, "agent_id": agent_id})

    timeout = _get_react_timeout()
    try:
        # ``asyncio.timeout(None)`` is a no-op, so an unset timeout disables
        # the guard rather than firing immediately.
        async with asyncio.timeout(timeout):
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
                    final_text = _extract_text_delta(result.content) or result.content
                    _record_react_loop(agent_id, tools, system_prompt_text,
                                       local_messages, result, status="ok")
                    return final_text

                # Tool calls → execute them, emit start/end events, continue the loop.
                local_messages.append(result)
                for tc in result.tool_calls:
                    _emit({"type": "tool_start", "tool": tc["name"], "iter": iteration})
                    output, _ = await _invoke_tool_safe(
                        tool_map, tc, iteration, _emit, tool_cache)
                    local_messages.append(
                        ToolMessage(content=str(output), tool_call_id=tc["id"])
                    )

            # max_iterations reached without a final report.
            final_text = _extract_text_delta(getattr(result, "content", "")) or "分析未完成（达到最大迭代次数）"
            _record_react_loop(agent_id, tools, system_prompt_text, local_messages,
                               result, status="incomplete",
                               degradation_reason="max_iterations")
            return final_text
    except TimeoutError:
        # A slow/stuck analyst must not hang the Quality Gate barrier —
        # degrade to a partial report so the pipeline keeps moving.
        final_text = (_extract_text_delta(getattr(result, "content", ""))
                      or "分析未完成（节点超时）")
        _emit({"type": "report_done", "iter": -1})
        _record_react_loop(agent_id, tools, system_prompt_text, local_messages,
                           result, status="degraded",
                           degradation_reason="timeout")
        return final_text
    except Exception as exc:
        # Any unexpected failure degrades to a failure report so the node
        # never crashes the barrier; the rest of the pipeline still runs.
        final_text = f"分析失败（{type(exc).__name__}: {exc}）"
        _emit({"type": "report_done", "iter": -1})
        _record_react_loop(agent_id, tools, system_prompt_text, local_messages,
                           result, status="degraded",
                           degradation_reason=f"exception:{type(exc).__name__}")
        return final_text


def _tools_to_openai_schema(tools: list) -> list[dict]:
    """Render LangChain tools as the OpenAI tool-schema list for SFT records.

    Returns ``[{"type": "function", "function": {"name", "description",
    "parameters": {...}}}]`` via langchain's ``convert_to_openai_tool``. On
    any failure (rare; exotic tool without a parseable schema) falls back to
    a minimal ``{"type":"function","function":{"name":...}}`` stub per tool so
    the record is still valid and the run never crashes.
    """
    schema: list[dict] = []
    for t in tools:
        try:
            from langchain_core.utils.function_calling import convert_to_openai_tool
            schema.append(convert_to_openai_tool(t))
        except Exception:
            schema.append({"type": "function", "function": {"name": getattr(t, "name", "unknown")}})
    return schema


def _record_react_loop(
    agent_id: str | None,
    tools: list,
    system_prompt_text: str,
    local_messages: list,
    final_result,  # AIMessage — the last assistant response (not yet in local_messages)
    status: str = "ok",
    degradation_reason: str = "",
) -> None:
    """Build SFT-format messages from a completed ReAct loop and submit to the recorder.

    *local_messages* contains the conversation history *excluding* the final
    assistant message (which is passed separately as *final_result* because
    ``run_react_loop`` only appends tool-calling turns to the list).

    *status* marks the outcome so the recorder can flag contaminated samples
    (P7): ``"ok"`` for a genuine final report, ``"incomplete"`` for a
    max-iteration cap, ``"degraded"`` for a timeout/exception. Non-ok records
    are kept for diagnosis but must be filtered out before SFT training.

    Every early-return path writes a diagnostic to the recorder's debug log
    (when a recorder is active) so there are never silent failures.
    """
    from tradingagents.agents.utils.sft_recorder import get_sft_recorder
    recorder = get_sft_recorder()

    # ── early-return: no recorder active ──
    if recorder is None:
        return

    # ── early-return: couldn't resolve agent ──
    if agent_id is None:
        recorder._log(
            "⚠ _record_react_loop: agent_id is None — _resolve_agent_id() "
            "returned None. This usually means the function is running outside "
            "a LangGraph context (unit test / Streamlit). system_prompt="
            f"{bool(system_prompt_text)} local_msgs={len(local_messages)}"
        )
        return

    # An empty system prompt means the prompt template wasn't rendered — the
    # SFT sample would lack a system message, degrading training quality. Mark
    # it incomplete rather than silently recording a degraded sample.
    if not system_prompt_text:
        recorder._log(
            f"⚠ _record_react_loop({agent_id}): system_prompt_text is EMPTY. "
            "The analyst node may not have rendered the prompt template. "
            "SFT messages will lack a system message — marked incomplete."
        )
        if status == "ok":
            status = "incomplete"
            degradation_reason = "empty_system_prompt"

    # No final assistant message means the loop never produced a report — the
    # caller is recording a fallback string, not real model output.
    if final_result is None and status == "ok":
        status = "incomplete"
        degradation_reason = "no_final_assistant_message"

    # Resolve agent_role from the registry.
    from tradingagents.agents.analysts.registry import ANALYST_BY_KEY
    spec = ANALYST_BY_KEY.get(agent_id)
    agent_role = spec.label if spec else agent_id

    recorder._log(
        f"_record_react_loop: agent_id={agent_id} role={agent_role} "
        f"status={status} reason={degradation_reason or '(none)'} "
        f"local_msgs={len(local_messages)} tools={[t.name for t in tools]} "
        f"final_result_type={type(final_result).__name__ if final_result is not None else 'None'}"
    )

    # Build tool_call_id → name lookup from AIMessage tool_calls.
    tool_call_id_to_name: dict[str, str] = {}
    for msg in local_messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_call_id_to_name[tc["id"]] = tc.get("name", "")
    if tool_call_id_to_name:
        recorder._log(f"  tool_call_id → name map: {tool_call_id_to_name}")

    # Assemble SFT messages (OpenAI tool-calling shape, see docs/SFT_FORMAT.md):
    # system → user → assistant(tool_calls, content=null) → tool(name,tool_call_id) → ... → assistant(final)
    sft_messages: list[dict] = []

    if system_prompt_text:
        sft_messages.append({"role": "system", "content": system_prompt_text})

    for msg in local_messages:
        role = _get_message_role(msg)
        if role == "user":
            sft_messages.append({"role": "user", "content": _msg_content(msg)})
        elif role == "assistant":
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                # Tool-call turn: content is null, tool_calls carry the
                # nested {type,id,function:{name,arguments}} shape. arguments
                # is kept as a dict (structured) per SFT_FORMAT.md.
                sft_messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "type": "function",
                            "id": tc["id"],
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["args"],
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                })
            else:
                sft_messages.append({"role": "assistant", "content": _msg_content(msg)})
        elif role == "tool":
            sft_messages.append({
                "role": "tool",
                "content": str(getattr(msg, "content", "")),
                "name": tool_call_id_to_name.get(getattr(msg, "tool_call_id", ""), ""),
                "tool_call_id": getattr(msg, "tool_call_id", ""),
            })
        else:
            recorder._log(f"  ⚠ unknown message role '{role}' — skipping message: {type(msg).__name__}")

    # Append the final assistant message (not in local_messages).
    if final_result is not None:
        final_content = _extract_text_delta(getattr(final_result, "content", "")) or str(getattr(final_result, "content", ""))
        sft_messages.append({"role": "assistant", "content": final_content})
        recorder._log(f"  appended final assistant message ({len(final_content)} chars)")
    else:
        recorder._log(f"  ⚠ final_result is None — no final assistant message appended!")

    tools_schema = _tools_to_openai_schema(tools)
    recorder.record(
        agent_id=f"{agent_id}_analyst",
        agent_role=agent_role,
        tools=tools_schema,
        messages=sft_messages,
        status=status,
        degradation_reason=degradation_reason,
    )


# ── downstream agent role mapping ──────────────────────────────────────────

_DOWNSTREAM_ROLES: dict[str, str] = {
    "bull": "多方辩手",
    "bear": "空方辩手",
    "quality_gate": "数据质量审核员",
    "aggressive": "激进风控分析师",
    "conservative": "保守风控分析师",
    "neutral": "中性风控分析师",
}


def _record_downstream(agent_id: str, prompt, response: str) -> None:
    """Record a single-turn (no-tools) downstream agent conversation for SFT.

    Called by ``stream_invoke`` for debate/risk/quality nodes.  *prompt* is
    always a plain string (the f-string the caller assembled); it becomes the
    sole ``user`` message.  *agent_id* is e.g. ``"bull"`` or ``"quality_gate"``.
    """
    if not agent_id or agent_id not in _DOWNSTREAM_ROLES:
        return

    from tradingagents.agents.utils.sft_recorder import get_sft_recorder
    recorder = get_sft_recorder()
    if recorder is None:
        return

    agent_role = _DOWNSTREAM_ROLES[agent_id]
    messages: list[dict] = [
        {"role": "system", "content": f"你是{agent_role}。"},
        {"role": "user", "content": str(prompt)},
        {"role": "assistant", "content": response},
    ]
    recorder.record(agent_id=agent_id, agent_role=agent_role, tools=[], messages=messages)


def _get_message_role(msg) -> str:
    """Classify a LangChain message as 'system', 'user', 'assistant', or 'tool'."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    if isinstance(msg, SystemMessage):
        return "system"
    if isinstance(msg, HumanMessage):
        return "user"
    if isinstance(msg, AIMessage):
        return "assistant"
    if isinstance(msg, ToolMessage):
        return "tool"
    return "unknown"


def _msg_content(msg) -> str:
    """Extract a plain-text content string from any LangChain message."""
    raw = getattr(msg, "content", "")
    return _extract_text_delta(raw) if raw else ""


        
