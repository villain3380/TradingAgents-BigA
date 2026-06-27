"""Tests for P3 (ReAct loop robustness) and P5 (debate routing decoupling).

P3 — run_react_loop must never crash the node:
- hallucinated tool name → error fed back as ToolMessage, loop continues
- tool.invoke raising → same recovery
- per-node timeout → degrade to a partial report, not a hang
- any unexpected exception → degrade to a failure report

P5 — debate routing must not depend on prose prefixes:
- investment debate routes on the explicit ``current_speaker`` token, so a
  localized prefix (e.g. "多方分析师：") no longer breaks routing
- risk debate routes on exact ``latest_speaker`` match
"""

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessageChunk

from tradingagents.agents.utils.agent_utils import run_react_loop
from tradingagents.graph.conditional_logic import ConditionalLogic


# ---------------------------------------------------------------------------
# Shared fake-chain helper (mirrors test_pluggable_analysts._stream_chain)
# ---------------------------------------------------------------------------


def _stream_chain(call_chunks: list[list]):
    calls = list(call_chunks)
    state = {"i": 0}

    class _Chain:
        async def astream(self, msgs):
            idx = state["i"]
            state["i"] += 1
            for c in calls[idx]:
                yield c

    return _Chain()


def _tool_call_chunk(name: str, args: dict | None = None, tc_id: str = "1"):
    return AIMessageChunk(
        content="",
        tool_call_chunks=[{
            "name": name,
            "args": json.dumps(args or {}),
            "id": tc_id,
            "index": 0,
        }],
    )


# ---------------------------------------------------------------------------
# P3.1 — hallucinated tool name + tool exception → recover, don't crash
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReactLoopToolErrorRecovery:
    def test_hallucinated_tool_name_feeds_error_and_continues(self):
        """LLM calls a non-existent tool → error string as ToolMessage,
        next turn the model produces a final report. Node must not crash."""
        tool = MagicMock()
        tool.name = "real_tool"  # only this exists; LLM hallucinated "ghost"
        tool.invoke.return_value = "DATA"
        chain = _stream_chain([
            [_tool_call_chunk("ghost", tc_id="1")],
            [AIMessageChunk(content="final report after recovery")],
        ])
        report = asyncio.run(run_react_loop(
            chain, tools=[tool], initial_message="hi", max_iterations=5))
        assert report == "final report after recovery"
        # The real tool was never invoked (the hallucinated name was rejected).
        tool.invoke.assert_not_called()

    def test_tool_invoke_exception_feeds_error_and_continues(self):
        """tool.invoke raises → error string as ToolMessage, loop continues."""
        tool = MagicMock()
        tool.name = "flaky"
        tool.invoke.side_effect = RuntimeError("boom")
        chain = _stream_chain([
            [_tool_call_chunk("flaky", tc_id="1")],
            [AIMessageChunk(content="recovered report")],
        ])
        report = asyncio.run(run_react_loop(
            chain, tools=[tool], initial_message="hi", max_iterations=5))
        assert report == "recovered report"
        tool.invoke.assert_called_once()

    def test_malformed_args_do_not_crash(self):
        """Malformed args (e.g. None instead of dict) → caught, fed back."""
        tool = MagicMock()
        tool.name = "needs_dict"
        tool.invoke.side_effect = TypeError("args must be dict")
        chain = _stream_chain([
            [_tool_call_chunk("needs_dict", tc_id="1")],
            [AIMessageChunk(content="ok after bad args")],
        ])
        report = asyncio.run(run_react_loop(
            chain, tools=[tool], initial_message="hi", max_iterations=5))
        assert report == "ok after bad args"


# ---------------------------------------------------------------------------
# P3.2 / P3.3 — timeout + unexpected exception → degrade, never raise
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReactLoopDegradesInsteadOfCrashing:
    def test_timeout_degrades_to_partial_report(self, monkeypatch):
        """When the loop exceeds react_loop_timeout, it returns a partial
        report instead of hanging the barrier."""
        from tradingagents.agents.utils import agent_utils

        async def _hang(*a, **kw):
            await asyncio.sleep(10)  # far beyond the timeout
            return AIMessageChunk(content="never")

        async def _fake_astream(self, msgs):
            yield await _hang()

        monkeypatch.setattr(agent_utils, "_get_react_timeout", lambda: 0.05)
        # Patch the chain's astream to hang.
        class _HangingChain:
            async def astream(self, msgs):
                await asyncio.sleep(10)
                yield AIMessageChunk(content="x")
                return

        report = asyncio.run(run_react_loop(
            _HangingChain(), tools=[], initial_message="hi", max_iterations=3))
        # Timeout path returns the specific 超时 marker, not the generic 失败 one.
        assert "超时" in report

    def test_unexpected_exception_degrades_to_failure_report(self, monkeypatch):
        """Any unexpected exception inside the loop → failure report, not raise."""
        from tradingagents.agents.utils import agent_utils

        class _BoomChain:
            async def astream(self, msgs):
                raise RuntimeError("chain blew up")
                yield  # pragma: no cover - generator semantics

        monkeypatch.setattr(agent_utils, "_get_react_timeout", lambda: None)
        report = asyncio.run(run_react_loop(
            _BoomChain(), tools=[], initial_message="hi", max_iterations=3))
        assert "失败" in report


# ---------------------------------------------------------------------------
# P5 — debate routing on explicit speaker token, not prose prefix
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDebateRoutingDecoupled:
    def _debate_state(self, count, speaker, response=""):
        return {"investment_debate_state": {
            "count": count,
            "current_speaker": speaker,
            "current_response": response,
        }}

    def test_bull_speaker_routes_to_bear(self):
        cl = ConditionalLogic(max_debate_rounds=3)
        assert cl.should_continue_debate(
            self._debate_state(count=0, speaker="bull")) == "Bear Researcher"

    def test_bear_speaker_routes_to_bull(self):
        cl = ConditionalLogic(max_debate_rounds=3)
        assert cl.should_continue_debate(
            self._debate_state(count=1, speaker="bear")) == "Bull Researcher"

    def test_count_exhausted_routes_to_research_manager(self):
        cl = ConditionalLogic(max_debate_rounds=1)  # 2*1 = 2 ends it
        assert cl.should_continue_debate(
            self._debate_state(count=2, speaker="bull")) == "Research Manager"

    def test_localized_prefix_does_not_break_routing(self):
        """Regression: a localized current_response prefix (多方分析师：) must
        NOT route bull→bull forever. Routing reads current_speaker, not the
        prose prefix."""
        cl = ConditionalLogic(max_debate_rounds=3)
        # current_response is localized Chinese, but speaker token is "bull".
        state = self._debate_state(
            count=0, speaker="bull", response="多方分析师：看多该股")
        assert cl.should_continue_debate(state) == "Bear Researcher"

    def test_empty_speaker_defaults_to_bull(self):
        cl = ConditionalLogic(max_debate_rounds=3)
        assert cl.should_continue_debate(
            self._debate_state(count=0, speaker="")) == "Bull Researcher"


@pytest.mark.unit
class TestRiskRoutingExactMatch:
    def _risk_state(self, count, speaker):
        return {"risk_debate_state": {
            "count": count, "latest_speaker": speaker,
        }}

    def test_aggressive_routes_to_conservative(self):
        cl = ConditionalLogic(max_risk_discuss_rounds=3)
        assert cl.should_continue_risk_analysis(
            self._risk_state(count=0, speaker="Aggressive")) == "Conservative Analyst"

    def test_conservative_routes_to_neutral(self):
        cl = ConditionalLogic(max_risk_discuss_rounds=3)
        assert cl.should_continue_risk_analysis(
            self._risk_state(count=1, speaker="Conservative")) == "Neutral Analyst"

    def test_neutral_routes_to_aggressive(self):
        cl = ConditionalLogic(max_risk_discuss_rounds=3)
        assert cl.should_continue_risk_analysis(
            self._risk_state(count=2, speaker="Neutral")) == "Aggressive Analyst"

    def test_count_exhausted_routes_to_pm(self):
        cl = ConditionalLogic(max_risk_discuss_rounds=1)  # 3*1 = 3 ends it
        assert cl.should_continue_risk_analysis(
            self._risk_state(count=3, speaker="Aggressive")) == "Portfolio Manager"
