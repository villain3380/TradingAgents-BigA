"""Tests for P7: SFT data must not be polluted by failed/degraded runs.

`_record_react_loop` and `SFTRecorder.record` now tag every record with a
``status`` (ok / incomplete / degraded) so downstream SFT pipelines can filter
on ``status == "ok"``. Failed runs are still recorded for diagnosis, but no
longer masquerade as successful training samples.
"""

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessageChunk

from tradingagents.agents.utils import agent_utils
from tradingagents.agents.utils.agent_utils import run_react_loop
from tradingagents.agents.utils import sft_recorder as sft_mod


# ---------------------------------------------------------------------------
# Fake-chain helper (mirrors test_pluggable_analysts._stream_chain)
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


def _tool_call_chunk(name, tc_id="1"):
    return AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": name, "args": "{}", "id": tc_id, "index": 0}],
    )


# ---------------------------------------------------------------------------
# run_react_loop exit paths tag the recorder with the right status
# ---------------------------------------------------------------------------


def _start_recorder():
    """Install a fresh recorder so run_react_loop records into it."""
    sft_mod._recorder = sft_mod.SFTRecorder("TEST", "2026-06-20")
    return sft_mod._recorder


def _stop_recorder():
    sft_mod._recorder = None


@pytest.mark.unit
class TestReactLoopSftStatus:
    def setup_method(self):
        _start_recorder()
        # run_react_loop skips recording when _resolve_agent_id() returns None
        # (no graph context). Force a valid analyst key so records are produced.
        self._orig_resolve = agent_utils._resolve_agent_id
        agent_utils._resolve_agent_id = lambda: "market"

    def teardown_method(self):
        _stop_recorder()
        agent_utils._resolve_agent_id = self._orig_resolve

    def test_normal_completion_is_ok(self):
        chain = _stream_chain([[AIMessageChunk(content="final report")]])
        asyncio.run(run_react_loop(chain, tools=[], initial_message="hi",
                                   max_iterations=3, system_prompt_text="SYS"))
        recs = sft_mod._recorder.records
        assert len(recs) == 1
        assert recs[0]["status"] == "ok"
        assert recs[0]["degradation_reason"] == ""

    def test_max_iterations_is_incomplete(self):
        tool = MagicMock()
        tool.name = "loop"
        tool.invoke.return_value = "x"
        chunk = _tool_call_chunk("loop")
        chain = _stream_chain([[chunk], [chunk]])
        asyncio.run(run_react_loop(chain, tools=[tool], initial_message="hi",
                                   max_iterations=2, system_prompt_text="SYS"))
        recs = sft_mod._recorder.records
        assert len(recs) == 1
        assert recs[0]["status"] == "incomplete"
        assert recs[0]["degradation_reason"] == "max_iterations"

    def test_timeout_is_degraded(self, monkeypatch):
        from tradingagents.agents.utils import agent_utils

        monkeypatch.setattr(agent_utils, "_get_react_timeout", lambda: 0.05)

        class _HangingChain:
            async def astream(self, msgs):
                await asyncio.sleep(10)
                yield AIMessageChunk(content="x")

        asyncio.run(run_react_loop(_HangingChain(), tools=[], initial_message="hi",
                                   max_iterations=3, system_prompt_text="SYS"))
        recs = sft_mod._recorder.records
        assert len(recs) == 1
        assert recs[0]["status"] == "degraded"
        assert recs[0]["degradation_reason"] == "timeout"

    def test_exception_is_degraded(self, monkeypatch):
        from tradingagents.agents.utils import agent_utils

        class _BoomChain:
            async def astream(self, msgs):
                raise RuntimeError("chain blew up")
                yield  # pragma: no cover

        monkeypatch.setattr(agent_utils, "_get_react_timeout", lambda: None)
        asyncio.run(run_react_loop(_BoomChain(), tools=[], initial_message="hi",
                                   max_iterations=3, system_prompt_text="SYS"))
        recs = sft_mod._recorder.records
        assert len(recs) == 1
        assert recs[0]["status"] == "degraded"
        assert "exception" in recs[0]["degradation_reason"]

    def test_empty_system_prompt_is_incomplete(self):
        """Even on a 'normal' exit, an empty system prompt downgrades to
        incomplete — the sample lacks a system message and is unfit for SFT."""
        chain = _stream_chain([[AIMessageChunk(content="final report")]])
        asyncio.run(run_react_loop(chain, tools=[], initial_message="hi",
                                   max_iterations=3, system_prompt_text=""))
        recs = sft_mod._recorder.records
        assert len(recs) == 1
        assert recs[0]["status"] == "incomplete"
        assert recs[0]["degradation_reason"] == "empty_system_prompt"


# ---------------------------------------------------------------------------
# Recorder.record stores status + degradation_reason; flush writes them
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecorderStatusFields:
    def test_record_stores_status_and_reason(self):
        rec = sft_mod.SFTRecorder("TEST", "2026-06-20")
        tools_schema = [{"type": "function", "function": {
            "name": "get_stock_data", "description": "Get stock data",
            "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}}]
        rec.record("market_analyst", "技术面分析师", tools_schema,
                   [{"role": "system", "content": "s"},
                    {"role": "user", "content": "u"},
                    {"role": "assistant", "content": "a"}],
                   status="degraded", degradation_reason="timeout")
        assert len(rec.records) == 1
        assert rec.records[0]["status"] == "degraded"
        assert rec.records[0]["degradation_reason"] == "timeout"
        # tools field keeps the full OpenAI schema (not just names)
        assert rec.records[0]["tools"] == tools_schema

    def test_record_defaults_to_ok(self):
        rec = sft_mod.SFTRecorder("TEST", "2026-06-20")
        rec.record("market_analyst", "技术面分析师", [],
                   [{"role": "system", "content": "s"},
                    {"role": "user", "content": "u"},
                    {"role": "assistant", "content": "a"}])
        assert rec.records[0]["status"] == "ok"
        assert rec.records[0]["degradation_reason"] == ""

    def test_flush_writes_status_into_jsonl(self, tmp_path, monkeypatch):
        # Redirect SFT output dir into a tmp path so we don't pollute ~/.tradingagents-biga
        monkeypatch.setattr(sft_mod.Path, "home", lambda: tmp_path)
        rec = sft_mod.SFTRecorder("TEST", "2026-06-20")
        rec.record("market_analyst", "技术面分析师", [],
                   [{"role": "system", "content": "s"},
                    {"role": "user", "content": "u"},
                    {"role": "assistant", "content": "a"}],
                   status="ok")
        rec.record("news_analyst", "新闻分析师", [],
                   [{"role": "system", "content": "s"},
                    {"role": "user", "content": "u"},
                    {"role": "assistant", "content": "a"}],
                   status="degraded", degradation_reason="timeout")
        path = rec.flush()
        assert path is not None
        with open(path, encoding="utf-8") as f:
            lines = [json.loads(l) for l in f]
        assert len(lines) == 2
        statuses = {l["agent_id"]: l["status"] for l in lines}
        assert statuses["market_analyst"] == "ok"
        assert statuses["news_analyst"] == "degraded"


# ---------------------------------------------------------------------------
# OpenAI tool-calling message shape (docs/SFT_FORMAT.md)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOpenAiMessageShape:
    def setup_method(self):
        _start_recorder()
        self._orig_resolve = agent_utils._resolve_agent_id
        agent_utils._resolve_agent_id = lambda: "market"

    def teardown_method(self):
        _stop_recorder()
        agent_utils._resolve_agent_id = self._orig_resolve

    def test_react_record_uses_openai_tool_call_shape(self):
        """A tool-call turn records content=null + nested function shape;
        the tool result carries both name and tool_call_id; tools field is
        the full OpenAI schema list."""
        from tradingagents.agents.utils.agent_utils import get_stock_data

        # Use the real LangChain tool so convert_to_openai_tool yields a full
        # schema (a MagicMock would hit the fallback stub path).
        tool = get_stock_data

        chain = _stream_chain([
            [_tool_call_chunk("get_stock_data", tc_id="call_1")],
            [AIMessageChunk(content="final report")],
        ])
        from langchain_core.messages import HumanMessage
        asyncio.run(run_react_loop(chain, tools=[tool],
                                   initial_message=HumanMessage(content="hi"),
                                   max_iterations=5, system_prompt_text="SYS"))

        rec = sft_mod._recorder.records[0]
        msgs = rec["messages"]

        # Sequence: system → user → assistant(tool_call) → tool → assistant(final)
        assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "assistant"]

        # assistant tool-call turn: content null, tool_calls nested
        tc_turn = msgs[2]
        assert tc_turn["content"] is None
        assert tc_turn["tool_calls"][0]["type"] == "function"
        assert tc_turn["tool_calls"][0]["id"] == "call_1"
        assert tc_turn["tool_calls"][0]["function"]["name"] == "get_stock_data"
        # arguments kept as a dict (structured), not a JSON string
        assert isinstance(tc_turn["tool_calls"][0]["function"]["arguments"], dict)

        # tool result: carries both name and tool_call_id
        tool_turn = msgs[3]
        assert tool_turn["name"] == "get_stock_data"
        assert tool_turn["tool_call_id"] == "call_1"

        # last message is the final assistant report
        assert msgs[-1] == {"role": "assistant", "content": "final report"}

        # tools field is the full OpenAI schema (not a bare name list)
        assert rec["tools"][0]["type"] == "function"
        assert rec["tools"][0]["function"]["name"] == "get_stock_data"
        assert "parameters" in rec["tools"][0]["function"]

    def test_no_tool_node_has_empty_tools_list(self):
        """A node that never calls a tool records tools: [] (downstream nodes)."""
        chain = _stream_chain([[AIMessageChunk(content="final report")]])
        asyncio.run(run_react_loop(chain, tools=[], initial_message="hi",
                                   max_iterations=3, system_prompt_text="SYS"))
        rec = sft_mod._recorder.records[0]
        assert rec["tools"] == []

    def test_record_field_order_matches_spec(self):
        """Top-level keys appear in the docs/SFT_FORMAT.md order."""
        rec = sft_mod.SFTRecorder("TEST", "2026-06-20")
        rec.record("market_analyst", "技术面分析师", [],
                   [{"role": "system", "content": "s"},
                    {"role": "user", "content": "u"},
                    {"role": "assistant", "content": "a"}])
        keys = list(rec.records[0].keys())
        assert keys == ["agent_id", "agent_role", "task", "status",
                        "degradation_reason", "messages", "tools"]
