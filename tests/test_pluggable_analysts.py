"""Tests for the pluggable parallel analyst architecture.

Covers the pluggability contract, parallel fan-out, message isolation, and
dynamic stage generation. Uses a fake LLM and stub analyst nodes so no API
keys or network are required.
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

# Ensure API key env vars exist so TradingAgentsGraph construction doesn't bail.
for _v in ("OPENAI_API_KEY", "ZHIPU_API_KEY", "DEEPSEEK_API_KEY"):
    os.environ.setdefault(_v, "placeholder")


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    """Point cache/results dirs at tmp so graph construction doesn't touch home."""
    from tradingagents.default_config import DEFAULT_CONFIG
    monkeypatch.setenv("TRADINGAGENTS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TRADINGAGENTS_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("TRADINGAGENTS_MEMORY_LOG_PATH", str(tmp_path / "mem.md"))
    yield


# ---------- registry ----------

def test_registry_has_seven_and_resolves_subset():
    from tradingagents.agents.analysts.registry import (
        ANALYST_REGISTRY,
        ANALYST_BY_KEY,
        DEFAULT_SELECTED,
        analyst_report_keys,
        resolve_selected,
    )
    assert len(ANALYST_REGISTRY) == 7
    assert len(DEFAULT_SELECTED) == 7
    assert set(ANALYST_BY_KEY) == set(DEFAULT_SELECTED)

    subset = resolve_selected(["market", "news"])
    assert [s.key for s in subset] == ["market", "news"]
    assert analyst_report_keys(["market", "news"]) == ["market_report", "news_report"]


def test_registry_empty_or_none_selects_all():
    from tradingagents.agents.analysts.registry import resolve_selected
    assert len(resolve_selected(None)) == 7
    assert len(resolve_selected([])) == 7


def test_registry_drops_unknown_keys():
    from tradingagents.agents.analysts.registry import resolve_selected
    assert [s.key for s in resolve_selected(["market", "nope"])] == ["market"]


def test_registry_specs_have_consistent_fields():
    from tradingagents.agents.analysts.registry import ANALYST_REGISTRY
    for spec in ANALYST_REGISTRY:
        assert spec.key and spec.label and spec.icon
        assert spec.report_field.endswith("_report")
        assert callable(spec.create)


# ---------- run_react_loop ----------

def _stream_chain(call_chunks: list[list]):
    """Build a fake chain whose .astream() yields a preset chunk list per call.

    Each call to .astream() pops the next list of AIMessageChunks. Mirrors how
    a real ``prompt | llm.bind_tools(tools)`` behaves under ``chain.astream()``.
    run_react_loop is now async and consumes ``chain.astream``.
    """
    from langchain_core.messages import AIMessageChunk
    calls = list(call_chunks)
    state = {"i": 0}

    class _Chain:
        async def astream(self, msgs):
            idx = state["i"]
            state["i"] += 1
            for c in calls[idx]:
                yield c

    return _Chain()


def test_run_react_loop_returns_content_when_no_tool_calls():
    import asyncio
    from tradingagents.agents.utils.agent_utils import run_react_loop
    from langchain_core.messages import AIMessageChunk

    chain = _stream_chain([[AIMessageChunk(content="final report text")]])
    report = asyncio.run(run_react_loop(chain, tools=[], initial_message="hi", max_iterations=3))
    assert report == "final report text"


def test_run_react_loop_executes_tools_then_returns():
    import asyncio
    import json
    from tradingagents.agents.utils.agent_utils import run_react_loop
    from langchain_core.messages import AIMessageChunk

    tool = MagicMock()
    tool.name = "lookup"
    tool.invoke.return_value = "DATA"
    chain = _stream_chain([
        [AIMessageChunk(content="", tool_call_chunks=[{"name": "lookup", "args": json.dumps({}), "id": "1", "index": 0}])],
        [AIMessageChunk(content="report after tool")],
    ])
    report = asyncio.run(run_react_loop(chain, tools=[tool], initial_message="hi", max_iterations=5))
    assert report == "report after tool"
    tool.invoke.assert_called_once_with({})


def test_run_react_loop_caps_at_max_iterations():
    import asyncio
    import json
    from tradingagents.agents.utils.agent_utils import run_react_loop
    from langchain_core.messages import AIMessageChunk

    tool = MagicMock()
    tool.name = "loop"
    tool.invoke.return_value = "x"
    # Every call requests the tool -> hits the iteration cap, returns last content.
    chunk = AIMessageChunk(content="partial", tool_call_chunks=[{"name": "loop", "args": json.dumps({}), "id": "1", "index": 0}])
    chain = _stream_chain([[chunk], [chunk]])
    report = asyncio.run(run_react_loop(chain, tools=[tool], initial_message="hi", max_iterations=2))
    assert report == "partial"


# ---------- topology: parallel + barrier + pluggability ----------

def _init_state():
    return {
        "messages": [("human", "000001")],
        "company_of_interest": "000001",
        "trade_date": "2026-06-20",
        "market_report": "", "sentiment_report": "", "news_report": "",
        "fundamentals_report": "", "policy_report": "", "hot_money_report": "",
        "lockup_report": "",
        "investment_debate_state": {
            "bull_history": "", "bear_history": "", "history": "",
            "current_response": "", "judge_decision": "", "count": 0,
        },
        "risk_debate_state": {
            "aggressive_history": "", "conservative_history": "", "neutral_history": "",
            "history": "", "latest_speaker": "",
            "current_aggressive_response": "", "current_conservative_response": "",
            "current_neutral_response": "", "judge_decision": "", "count": 0,
        },
    }


def _build_fanout_graph(selected):
    """Minimal graph: Send fan-out -> analysts -> gate -> END."""
    from tradingagents.agents.analysts.registry import resolve_selected
    from tradingagents.agents.utils.agent_states import AgentState

    active = resolve_selected(selected)
    starts = {}

    def make_node(spec, slow):
        def node(state):
            starts[spec.key] = time.time()
            time.sleep(slow)
            return {spec.report_field: f"report-{spec.key}"}
        return node

    wf = StateGraph(AgentState)
    for i, s in enumerate(active):
        wf.add_node(f"{s.key}_analyst", make_node(s, slow=0.2 if i == 1 else 0.02))
    wf.add_node("gate", lambda st: {"data_quality_summary": "ok"})

    def fan_out(state):
        return [
            Send(f"{s.key}_analyst", {
                "company_of_interest": state["company_of_interest"],
                "trade_date": state["trade_date"],
            })
            for s in active
        ]

    wf.add_conditional_edges(START, fan_out)
    for s in active:
        wf.add_edge(f"{s.key}_analyst", "gate")
    wf.add_edge("gate", END)
    return wf.compile(), starts


def test_analysts_run_in_parallel_and_barrier_waits():
    g, starts = _build_fanout_graph(["market", "news"])
    final = g.invoke(_init_state(), config={"recursion_limit": 50})
    assert final["market_report"] == "report-market"
    assert final["news_report"] == "report-news"
    # Same superstep: starts within 100ms despite 180ms duration difference.
    assert abs(starts["market"] - starts["news"]) < 0.1


def test_deselected_analysts_do_not_run():
    g, starts = _build_fanout_graph(["market"])
    final = g.invoke(_init_state(), config={"recursion_limit": 50})
    assert final["market_report"] == "report-market"
    assert final["news_report"] == ""  # never ran
    assert "news" not in starts


# ---------- full graph construction ----------

class _FakeLLM:
    def bind_tools(self, tools):
        return self

    def invoke(self, msgs, **kw):
        return AIMessage(content="mock")

    def with_structured_output(self, *a, **k):
        return self

    @property
    def model_name(self):
        return "mock"


def test_full_graph_compiles_with_subset_and_drops_old_nodes():
    fake_client = MagicMock()
    fake_client.get_llm.return_value = _FakeLLM()
    with patch("tradingagents.llm_clients.create_llm_client", return_value=fake_client), \
         patch("tradingagents.llm_clients.factory.create_llm_client", return_value=fake_client):
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        config = dict(DEFAULT_CONFIG)
        config.update({
            "llm_provider": "openai", "deep_think_llm": "gpt-5",
            "quick_think_llm": "gpt-5", "output_language": "Chinese",
            "max_debate_rounds": 0, "max_risk_discuss_rounds": 0,
            "checkpoint_enabled": False,
        })
        g = TradingAgentsGraph(
            selected_analysts=["market", "news"],
            debug=False,
            config=config,
        )
    nodes = set(g.graph.get_graph().nodes.keys())
    assert "market_analyst" in nodes and "news_analyst" in nodes
    assert "social_analyst" not in nodes  # deselected
    assert "Quality Gate" in nodes and "Portfolio Manager" in nodes
    # Old per-analyst machinery must be gone.
    assert not any("Msg Clear" in str(n) or "tools_" in str(n) for n in nodes)


# ---------- quality gate only grades active ----------

def test_quality_gate_only_grades_active_analysts():
    import asyncio
    from tradingagents.agents.analysts.registry import resolve_selected
    from tradingagents.agents.quality_gate import create_quality_gate

    active = resolve_selected(["market", "news"])
    gate = create_quality_gate(llm=MagicMock(), active=active)
    # Only market has content; news empty. Deselected analysts must not appear.
    state = {
        "trade_date": "2026-06-20",
        "company_of_interest": "000001",
        "market_report": "x" * 250 + " | --- \n table",
        "news_report": "",
        # Deselected fields present but must be ignored:
        "sentiment_report": "", "fundamentals_report": "",
    }
    out = asyncio.run(gate(state))
    summary = out["data_quality_summary"]
    assert "技术分析师" in summary
    assert "新闻分析师" in summary
    assert "情绪分析师" not in summary  # deselected -> not graded
    assert "基本面分析师" not in summary


# ---------- web: dynamic pipeline stages ----------

def test_build_pipeline_stages_reflects_selection():
    from web.progress import build_pipeline_stages
    full = build_pipeline_stages(None)
    assert [s["id"] for s in full[:7]] == [
        "market", "social", "news", "fundamentals", "policy", "hot_money", "lockup",
    ]
    sub = build_pipeline_stages(["market", "news"])
    assert [s["id"] for s in sub] == ["market", "news", "quality_gate", "debate", "trader", "risk", "pm"]
