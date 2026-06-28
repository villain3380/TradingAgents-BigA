"""SFT data recorder — captures complete agent I/O for fine-tuning dataset generation.

Each analysis task (one ``propagate`` call) produces two files under
``~/.tradingagents-biga/sft/``:
- ``{ticker}_{date}_{timestamp}.jsonl`` — the training data
- ``{ticker}_{date}_{timestamp}_debug.log`` — comprehensive debug log

Usage::

    from tradingagents.agents.utils.sft_recorder import (
        start_sft_recording, get_sft_recorder, stop_sft_recording,
    )
    start_sft_recording("300308", "2026-06-26")
    ...
    recorder = get_sft_recorder()
    if recorder:
        recorder.record(agent_id="market_analyst", agent_role="技术分析师",
                        tools=["get_stock_data"], messages=[...])
    ...
    path = stop_sft_recording()  # writes JSONL, returns path or None
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_recorder: SFTRecorder | None = None

# ── helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    """Timestamp with ms precision for debug log entries."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _content_preview(text: str, max_len: int = 200) -> str:
    """First *max_len* chars of *text*, with newlines collapsed for log readability."""
    flat = str(text)[:max_len].replace("\n", "\\n").replace("\r", "")
    if len(str(text)) > max_len:
        flat += f"… [{len(str(text))} total chars]"
    return flat


def _message_preview(msg: dict, max_len: int = 120) -> str:
    """Single-line summary of one SFT-format message."""
    role = msg.get("role", "?")
    if role == "system":
        return f"system ({len(msg.get('content',''))} chars)"
    if role == "user":
        return f"user content={_content_preview(msg.get('content',''), max_len)}"
    if role == "tool":
        tid = msg.get("tool_call_id", "")
        name = msg.get("name", "?")
        return f"tool name={name} id={tid[:20]}… content={_content_preview(msg.get('content',''), max_len)}"
    if role == "assistant":
        tcs = msg.get("tool_calls")
        if tcs:
            # OpenAI shape: tc["function"]["name"]
            names = [tc.get("function", {}).get("name", "?") for tc in tcs]
            return f"assistant(tool_calls) → {names}"
        return f"assistant(final) content={_content_preview(msg.get('content',''), max_len)}"
    return f"{role} {_content_preview(str(msg), max_len)}"


# ── format validation ────────────────────────────────────────────────────────

def _validate_messages(messages: list[dict]) -> list[str]:
    """Check *messages* against SFT_FORMAT.md rules. Returns list of warnings."""
    warnings: list[str] = []
    if not messages:
        warnings.append("EMPTY: messages list is empty")
        return warnings

    roles = [m.get("role", "") for m in messages]
    contents = [m.get("content", "") for m in messages]

    # Rule 1: first is system
    if roles[0] != "system":
        warnings.append(f"RULE-1: first message is '{roles[0]}', expected 'system'")

    # Rule 2: second is user
    if len(roles) > 1 and roles[1] != "user":
        warnings.append(f"RULE-2: second message is '{roles[1]}', expected 'user'")

    # Rule 3: strict alternation after system
    for i in range(2, len(roles)):
        if roles[i] == roles[i - 1]:
            warnings.append(
                f"RULE-3: duplicate role '{roles[i]}' at positions {i-1} and {i}"
            )

    # Rule 4: last is assistant
    if roles[-1] != "assistant":
        warnings.append(f"RULE-4: last message is '{roles[-1]}', expected 'assistant'")

    # Rule 5: tool messages must have tool_call_id matching a prior assistant's tool_calls
    for i, m in enumerate(messages):
        if m.get("role") == "tool":
            # Find previous assistant message
            found = False
            for j in range(i - 1, -1, -1):
                prev = messages[j]
                if prev.get("role") == "assistant" and prev.get("tool_calls"):
                    for tc in prev["tool_calls"]:
                        if tc.get("id") == m["tool_call_id"]:
                            found = True
                            break
                    break
            if not found:
                warnings.append(
                    f"RULE-5: tool message at idx {i} (id={m['tool_call_id'][:20]}…) "
                    f"has no matching tool_call in prior assistant message"
                )

    # Content sanity
    for i, m in enumerate(messages):
        if m.get("role") == "assistant":
            # content may be null on a tool-call turn (legal OpenAI shape);
            # only flag when there's neither text nor tool_calls.
            content = m.get("content")
            has_text = bool(content) and bool(str(content).strip())
            has_tools = bool(m.get("tool_calls"))
            if not has_text and not has_tools:
                warnings.append(f"SANITY: assistant at idx {i} has neither content nor tool_calls")
            if has_text and has_tools:
                pass  # legal — model can emit text before/alongside tool calls
        if m.get("role") == "user":
            if not str(m.get("content", "")).strip():
                warnings.append(f"SANITY: user at idx {i} has empty content")

    return warnings


# ── SFTRecorder ──────────────────────────────────────────────────────────────

class SFTRecorder:
    """Accumulates per-agent conversation records and flushes them to a JSONL file.

    Every action is mirrored to a ``_debug.log`` file on disk so that failures
    during an expensive (multi-million-token) analysis run are fully diagnosable
    without re-running.
    """

    def __init__(self, ticker: str, trade_date: str) -> None:
        self.ticker = ticker
        self.trade_date = trade_date
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.records: list[dict[str, Any]] = []
        self._debug_fh = None
        self._record_count = 0

        # Open debug log alongside the JSONL output.
        out_dir = Path.home() / ".tradingagents-biga" / "sft"
        out_dir.mkdir(parents=True, exist_ok=True)
        debug_path = out_dir / f"{ticker}_{trade_date}_{self.timestamp}_debug.log"
        self._debug_path = str(debug_path)
        self._debug_fh = open(debug_path, "w", encoding="utf-8")

        self._log("=" * 72)
        self._log(f"SFT RECORDING SESSION START")
        self._log(f"  ticker    = {ticker}")
        self._log(f"  trade_date= {trade_date}")
        self._log(f"  timestamp = {self.timestamp}")
        self._log(f"  debug_log = {self._debug_path}")
        self._log(f"  pid       = {os.getpid()}")
        self._log(f"  python    = {sys.version}")
        self._log("=" * 72)

    # ── internal ──────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        """Write a timestamped line to the debug log and flush immediately."""
        try:
            line = f"[{_now()}] {msg}\n"
            self._debug_fh.write(line)
            self._debug_fh.flush()
        except Exception:
            pass  # must never crash the agent run

    def _log_exception(self, ctx: str) -> None:
        """Log the current exception with traceback."""
        exc = traceback.format_exc()
        self._log(f"EXCEPTION in {ctx}:")
        for line in exc.splitlines():
            self._log(f"  | {line}")

    # ── public ────────────────────────────────────────────────────────────

    def record(
        self,
        agent_id: str,
        agent_role: str,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        *,
        status: str = "ok",
        degradation_reason: str = "",
    ) -> None:
        """Append one agent's complete conversation to the recording buffer.

        ``tools`` is the OpenAI tool-schema list
        (``[{"type": "function", "function": {"name", "description",
        "parameters": {...}}}]``) for ReAct agents, or ``[]`` for no-tool
        nodes. ``messages`` follows the OpenAI tool-calling message shape
        (see docs/SFT_FORMAT.md): assistant tool-call turns carry
        ``content: null`` and ``tool_calls``; tool results carry both
        ``tool_call_id`` and ``name``.

        ``status`` marks the run's outcome so downstream SFT pipelines can
        filter out contaminated samples without losing diagnostic data:

        - ``"ok"``         — the agent produced a genuine final report
        - ``"incomplete"`` — hit max_iterations / empty system prompt / no
                              final assistant message; the "answer" is a
                              fixed fallback string, not real model output
        - ``"degraded"``   — node timed out or raised; P3 degraded the node
                              to a failure report instead of crashing

        Non-``ok`` records are STILL written (debug value) but carry
        ``degradation_reason``; train on ``status == "ok"`` only.
        """
        self._record_count += 1
        idx = self._record_count

        tool_names = [t.get("function", {}).get("name", "?") for t in tools]

        self._log("-" * 56)
        self._log(f"RECORD #{idx}: agent_id={agent_id}  role={agent_role}  tools={tool_names}")
        self._log(f"  status={status}  reason={degradation_reason or '(none)'}")
        self._log(f"  message count: {len(messages)}")

        # Role sequence for quick scan
        role_seq = " → ".join(m.get("role", "?") for m in messages)
        self._log(f"  role sequence: {role_seq}")

        # Per-message preview
        for i, m in enumerate(messages):
            self._log(f"  msg[{i}]: {_message_preview(m)}")

        # Validate
        warnings = _validate_messages(messages)
        if warnings:
            self._log(f"  ⚠ VALIDATION WARNINGS ({len(warnings)}):")
            for w in warnings:
                self._log(f"    - {w}")
        else:
            self._log(f"  ✓ format validation passed")

        # Check for empty or obviously bad content
        for i, m in enumerate(messages):
            if m.get("role") == "system" and not m.get("content", "").strip():
                self._log(f"  ⚠ msg[{i}]: system message has EMPTY content!")
            if m.get("role") == "assistant" and i == len(messages) - 1:
                # Final assistant must have real text content. A tool-call
                # turn (content null + tool_calls) is fine mid-conversation
                # but must NOT be the last message.
                content = m.get("content")
                if not content or not str(content).strip():
                    self._log(f"  ⚠ msg[{i}]: FINAL assistant message has EMPTY content!")

        # Actually store — field order matches docs/SFT_FORMAT.md
        try:
            rec = {
                "agent_id": agent_id,
                "agent_role": agent_role,
                "task": {"ticker": self.ticker, "trade_date": self.trade_date},
                "status": status,
                "degradation_reason": degradation_reason,
                "messages": messages,
                "tools": tools,
            }
            self.records.append(rec)

            # Verify it's JSON-serializable
            json.dumps(rec, ensure_ascii=False)
            self._log(f"  ✓ stored successfully (JSON serializable)")
        except Exception:
            self._log_exception(f"record #{idx}")
            self._log(f"  ❌ FAILED to serialize record #{idx}!")

        self._log(f"  total records so far: {len(self.records)}")

    def flush(self) -> str | None:
        """Write all accumulated records to a JSONL file.

        Returns the output path, or ``None`` when there is nothing to write.
        """
        self._log("=" * 72)
        self._log(f"FLUSH: {len(self.records)} records to write")

        if not self.records:
            self._log("  (nothing to flush — no records collected)")
            self._close_debug()
            return None

        try:
            out_dir = Path.home() / ".tradingagents-biga" / "sft"
            out_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{self.ticker}_{self.trade_date}_{self.timestamp}.jsonl"
            path = out_dir / fname

            with open(path, "w", encoding="utf-8") as f:
                for i, rec in enumerate(self.records):
                    line = json.dumps(rec, ensure_ascii=False) + "\n"
                    f.write(line)
                    f.flush()  # flush each line so partial data survives crashes

            file_size = path.stat().st_size
            self._log(f"  ✅ written to: {path}")
            self._log(f"  file size: {file_size} bytes ({file_size/1024:.1f} KB)")
            self._log(f"  records: {len(self.records)}")

            # Summary per agent
            agent_counts: dict[str, int] = {}
            for rec in self.records:
                aid = rec.get("agent_id", "?")
                agent_counts[aid] = agent_counts.get(aid, 0) + 1
            self._log(f"  per agent: {agent_counts}")

            # Status breakdown — surfaces SFT data contamination at a glance.
            # Only status=="ok" records are safe to train on; non-ok are kept
            # for diagnosis (P7: stop polluting the SFT flywheel).
            status_counts: dict[str, int] = {}
            for rec in self.records:
                s = rec.get("status", "ok")
                status_counts[s] = status_counts.get(s, 0) + 1
            self._log(f"  status breakdown: {status_counts}")
            non_ok = sum(c for s, c in status_counts.items() if s != "ok")
            if non_ok:
                self._log(f"  ⚠ {non_ok} non-ok record(s) — filter on status==\"ok\" before SFT training")
            logger.info("SFT status breakdown: %s (train on ok only)", status_counts)

            # Message count stats
            msg_counts = [len(r["messages"]) for r in self.records]
            self._log(f"  messages/agent: min={min(msg_counts)} max={max(msg_counts)} avg={sum(msg_counts)/len(msg_counts):.1f}")

            # Check for agents with very few messages (probably errors)
            for rec in self.records:
                if len(rec["messages"]) <= 3:
                    self._log(f"  ⚠ short conversation: {rec['agent_id']} has only {len(rec['messages'])} messages")

            logger.info("SFT recording saved to %s (%d agents, %d KB)",
                        path, len(self.records), file_size // 1024)
            self._close_debug()
            return str(path)

        except Exception:
            self._log_exception("flush")
            self._log("  ❌ FLUSH FAILED!")
            self._close_debug()
            raise

    def _close_debug(self) -> None:
        """Close the debug log file handle."""
        if self._debug_fh is not None:
            self._log(f"SFT RECORDING SESSION END")
            self._log("=" * 72)
            try:
                self._debug_fh.close()
            except Exception:
                pass
            self._debug_fh = None


# ── module-level API ─────────────────────────────────────────────────────────

def _canary(msg: str) -> None:
    """Write a one-line diagnostic to a hardcoded canary file in the user home dir.

    This is the most-defensive logging possible: just ``open().write()`` with
    no dependencies, so we can tell whether ``start_sft_recording`` is ever
    reached — and if so, how far it gets before failing.
    """
    try:
        p = Path.home() / ".tradingagents-biga" / "sft" / "_canary.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{_now()}] [{os.getpid()}] {msg}\n")
    except Exception:
        pass  # must never propagate


def start_sft_recording(ticker: str, trade_date: str) -> None:
    """Begin a new SFT recording session for *ticker* on *trade_date*.

    No-op when ``sft_record`` is disabled in config or a session is already
    active (the existing session is left untouched to avoid data loss).
    """
    global _recorder

    _canary(f"start_sft_recording called: ticker={ticker} trade_date={trade_date}")

    # Already recording — don't silently overwrite.
    if _recorder is not None:
        _canary(f"SKIP: already recording for {_recorder.ticker} (debug={_recorder._debug_path})")
        logger.info("SFT recorder: session already active for %s, skipping start (existing debug: %s)",
                    _recorder.ticker, _recorder._debug_path)
        return

    # Check the config toggle (default: enabled).
    try:
        from tradingagents.dataflows.config import get_config
        cfg = get_config()
        sft_enabled = cfg.get("sft_record", True)
        _canary(f"config check: sft_record={sft_enabled} cfg_keys={sorted(cfg.keys())}")
        if not sft_enabled:
            _canary("SKIP: sft_record=False in config")
            logger.info("SFT recorder: DISABLED via config sft_record=False — no JSONL will be generated")
            return
    except Exception as exc:
        _canary(f"config check FAILED: {exc}")
        pass  # config not yet initialised — proceed anyway

    try:
        _recorder = SFTRecorder(ticker, trade_date)
        _canary(f"CREATED recorder: debug_log={_recorder._debug_path}")
        logger.info("SFT recorder: started for %s on %s (debug log: %s)",
                    ticker, trade_date, _recorder._debug_path)
    except Exception as exc:
        _canary(f"FAILED to create SFTRecorder: {exc}")
        import traceback
        _canary(traceback.format_exc())
        # Don't re-raise — recording failure must never crash the agent run.


def get_sft_recorder() -> SFTRecorder | None:
    """Return the active recorder, or ``None`` when recording is inactive."""
    return _recorder


def stop_sft_recording() -> str | None:
    """Flush and tear down the active recording session.

    Returns the path to the written JSONL file, or ``None``.
    Idempotent — safe to call when no session is active.
    """
    global _recorder
    if _recorder is None:
        return None
    path = _recorder.flush()
    if path:
        logger.info("SFT recorder: JSONL saved to %s", path)
    else:
        logger.info("SFT recorder: stopped — no records collected (0 agents ran or all failed)")
    _recorder = None
    return path
