"""FastAPI server exposing the TradingAgents pipeline as SSE for the TS frontend.

Runs as a separate process from Streamlit (``tradingagents-web``). Reuses the
same ``TradingAgentsGraph`` core; only the streaming transport differs:
- Streamlit path: ``graph.stream`` (sync, polled ProgressTracker)
- API path:       ``graph.astream(stream_mode=["custom","updates"])`` (async, SSE)

Token events come from ``run_react_loop``'s ``get_stream_writer`` calls
(custom stream); stage completions are derived from the ``updates`` stream.
Both are merged into a single SSE response per run.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
import uuid
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# Load .env once at import so ZHIPU_API_KEY / BACKEND_URL etc. are visible to
# the LLM clients — mirrors web/app.py's load_dotenv at startup.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)

from tradingagents.agents.analysts.registry import resolve_selected
from tradingagents.agents.utils.sft_recorder import start_sft_recording, stop_sft_recording
from tradingagents.dataflows.utils import safe_ticker_component
from web.api.stages import detect_stage_events

app = FastAPI(title="TradingAgents API")

# Dev: the Vite frontend (":5173") calls this API (":8000"); allow it. In prod
# the built frontend is served from this same origin so CORS is unused.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    ticker: str
    trade_date: str
    analysts: Optional[list[str]] = None
    config: Optional[dict[str, Any]] = None


# In-memory run registry: run_id -> {queue, task}. A run lives only for the
# duration of its SSE connection; process restart drops everything. The task
# reference lets us cancel an in-flight graph run (debugging — stop early to
# save tokens/time) when the user hits Stop.
_runs: dict[str, dict] = {}

# Completed-run reports: run_id -> {final_state, ticker, trade_date, signal}.
# Kept SEPARATE from _runs so closing the SSE connection (which pops _runs)
# does NOT delete the report — the user clicks "download" after the stream
# ends, so the report must survive the SSE teardown. Single-user, so we just
# keep the most recent handful to bound memory.
_reports: dict[str, dict] = {}
_MAX_REPORTS = 20


def _analyst_meta(selected: list[str] | None) -> list[dict]:
    return [
        {"key": s.key, "label": s.label, "icon": s.icon, "report_field": s.report_field}
        for s in resolve_selected(selected)
    ]


def _default_config(overrides: dict | None) -> dict:
    """Build a run config, layering: DEFAULT_CONFIG < .env < settings.json < request.

    The LLM provider/model can be set via .env (LLM_PROVIDER, ...) for headless
    runs, or via settings.json's default_provider + per-provider selection (set
    from the TS frontend). Per-request ``overrides`` (the frontend's current
    selection) always win on top.
    """
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.settings import get_default_provider, get_provider_selection

    cfg = dict(DEFAULT_CONFIG)

    # .env-driven defaults (absent → keep DEFAULT_CONFIG's openai/gpt-5).
    if os.getenv("LLM_PROVIDER"):
        cfg["llm_provider"] = os.getenv("LLM_PROVIDER")
    if os.getenv("DEEP_THINK_LLM"):
        cfg["deep_think_llm"] = os.getenv("DEEP_THINK_LLM")
    if os.getenv("QUICK_THINK_LLM"):
        cfg["quick_think_llm"] = os.getenv("QUICK_THINK_LLM")
    if os.getenv("BACKEND_URL"):
        cfg["backend_url"] = os.getenv("BACKEND_URL")

    # settings.json default provider + its saved selection (overrides .env, so
    # the frontend's "set as default" actually takes effect for headless calls).
    dp = get_default_provider()
    if dp:
        cfg["llm_provider"] = dp
        sel = get_provider_selection(dp)
        if sel["quick_think_llm"]:
            cfg["quick_think_llm"] = sel["quick_think_llm"]
        if sel["deep_think_llm"]:
            cfg["deep_think_llm"] = sel["deep_think_llm"]
        if sel["backend_url"]:
            cfg["backend_url"] = sel["backend_url"]

    if overrides:
        cfg.update(overrides)
    # The API always streams; keep checkpoints off by default to avoid
    # astream+SqliteSaver interactions during the skeleton phase.
    cfg["checkpoint_enabled"] = False
    return cfg


@app.get("/api/analysts")
def list_analysts() -> list[dict]:
    """Return all analyst metadata so the frontend can render cards."""
    return _analyst_meta(None)


# Provider display order + names — mirrors web/components/sidebar.py sidebar.
_PROVIDERS: list[dict] = [
    {"key": "minimax", "label": "MiniMax"},
    {"key": "deepseek", "label": "DeepSeek"},
    {"key": "qwen", "label": "通义千问 Qwen"},
    {"key": "glm", "label": "智谱 GLM"},
    {"key": "huoshan", "label": "火山方舟"},
    {"key": "openai", "label": "OpenAI"},
    {"key": "anthropic", "label": "Anthropic"},
    {"key": "google", "label": "Google Gemini"},
    {"key": "xai", "label": "xAI Grok"},
    {"key": "openrouter", "label": "OpenRouter（聚合·填 vendor/model 形式 ID）"},
    {"key": "ollama", "label": "Ollama（本地）"},
]


@app.get("/api/providers")
def list_providers() -> dict:
    """Return LLM provider list + per-provider model options + saved selections.

    Built-in providers come from MODEL_OPTIONS; custom providers (user-defined
    OpenAI-compatible endpoints) come from settings.json and appear at the end.
    Each provider carries the user's saved selection + a ``custom`` flag
    (custom providers can be edited/deleted; built-ins cannot). API keys are
    NOT included — they live in .env.
    """
    from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS
    from tradingagents.settings import load_settings

    saved = load_settings()
    saved_providers = saved.get("providers", {})
    saved_customs = saved.get("custom_providers", {}) or {}

    providers = []
    # Built-in providers (fixed order + label).
    for p in _PROVIDERS:
        key = p["key"]
        opts = MODEL_OPTIONS.get(key, {})
        sel = saved_providers.get(key, {})
        providers.append({
            "key": key,
            "label": p["label"],
            "custom": False,
            "quick": [{"label": lbl, "value": val} for lbl, val in opts.get("quick", [])],
            "deep": [{"label": lbl, "value": val} for lbl, val in opts.get("deep", [])],
            "selected": {
                "quick_think_llm": sel.get("quick_think_llm", ""),
                "deep_think_llm": sel.get("deep_think_llm", ""),
                "backend_url": sel.get("backend_url", ""),
            },
            # has_key tells the frontend to show "已设置" without leaking the key.
            "has_key": bool(sel.get("api_key")),
        })
    # Custom providers (user-defined). No preset model list — always free-text.
    for name, cp in saved_customs.items():
        sel = saved_providers.get(name, {})
        providers.append({
            "key": name,
            "label": name,
            "custom": True,
            "base_url": cp.get("base_url", ""),
            "api_key_env": cp.get("api_key_env", ""),
            "quick": [],
            "deep": [],
            "selected": {
                "quick_think_llm": sel.get("quick_think_llm", ""),
                "deep_think_llm": sel.get("deep_think_llm", ""),
                "backend_url": sel.get("backend_url", "") or cp.get("base_url", ""),
            },
            "has_key": bool(sel.get("api_key")),
        })
    return {"providers": providers, "default_provider": saved.get("default_provider")}


class ProviderSelection(BaseModel):
    quick_think_llm: str
    deep_think_llm: str
    backend_url: str = ""
    api_key: Optional[str] = None  # plaintext; stored in settings.json (home dir, not in repo)


@app.put("/api/providers/{provider}")
def save_provider_selection(provider: str, sel: ProviderSelection) -> dict:
    """Persist the user's model/base_url/api_key selection for one provider.

    Single-user: writes straight to ~/.tradingagents-biga/settings.json (home dir,
    never committed). api_key is stored plaintext — same trust level as .env.
    """
    from tradingagents.settings import set_provider_selection
    set_provider_selection(
        provider,
        quick_think_llm=sel.quick_think_llm,
        deep_think_llm=sel.deep_think_llm,
        backend_url=sel.backend_url or None,
        api_key=sel.api_key,
    )
    return {"saved": provider}


class CustomProviderReq(BaseModel):
    name: str
    base_url: str
    api_key_env: str = ""
    quick_think_llm: str = ""
    deep_think_llm: str = ""
    api_key: Optional[str] = None


@app.post("/api/providers/custom")
def create_custom_provider(req: CustomProviderReq) -> dict:
    """Create (or update) a custom OpenAI-compatible provider.

    The user gives a name, base_url, and either an api_key (stored here) or an
    api_key_env (env-var name for .env users, as fallback). The real key, if
    provided via api_key, lives in settings.json (home dir, not committed).
    """
    from tradingagents.settings import upsert_custom_provider, set_provider_selection
    try:
        upsert_custom_provider(req.name.strip(), req.base_url, (req.api_key_env or "").strip())
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
    set_provider_selection(
        req.name.strip(),
        quick_think_llm=req.quick_think_llm or None,
        deep_think_llm=req.deep_think_llm or None,
        backend_url=req.base_url or None,
        api_key=req.api_key,
    )
    return {"saved": req.name.strip()}


@app.put("/api/providers/custom/{name}")
def update_custom_provider(name: str, req: CustomProviderReq) -> dict:
    """Edit an existing custom provider's base_url / key env / models.

    The ``name`` in the body wins (allows rename); upsert handles create-or-
    update, so this is the same operation as POST.
    """
    return create_custom_provider(req)


@app.delete("/api/providers/custom/{name}")
def remove_custom_provider(name: str) -> dict:
    """Delete a custom provider (built-ins cannot be deleted)."""
    from tradingagents.settings import delete_custom_provider
    delete_custom_provider(name)
    return {"deleted": name}


class DefaultProviderReq(BaseModel):
    provider: Optional[str] = None


@app.put("/api/settings/default-provider")
def set_default(req: DefaultProviderReq) -> dict:
    """Set (or clear with null) the default provider."""
    from tradingagents.settings import set_default_provider
    set_default_provider(req.provider)
    return {"default_provider": req.provider}


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest) -> dict:
    """Start a run in the background; return run_id immediately."""
    # Canary: proves this endpoint code is actually the updated version.
    from tradingagents.agents.utils.sft_recorder import _canary
    _canary(f"ENDPOINT /api/analyze hit: ticker={req.ticker} date={req.trade_date}")

    run_id = uuid.uuid4().hex[:12]
    queue: asyncio.Queue = asyncio.Queue()
    # Register the run BEFORE creating the task. _run_graph's first action is
    # _runs.get(run_id); if create_task runs first, the task can start before
    # this dict assignment lands, see run=None, and silently no-op. Setting
    # the record first guarantees _run_graph always finds it.
    _runs[run_id] = {"queue": queue, "task": None}
    task = asyncio.create_task(_run_graph(run_id, req))
    _runs[run_id]["task"] = task
    return {
        "run_id": run_id,
        "ticker": req.ticker,
        "trade_date": req.trade_date,
        "analysts": _analyst_meta(req.analysts),
    }


async def _run_graph(run_id: str, req: AnalyzeRequest) -> None:
    """Execute the pipeline, pushing SSE items into the run's queue."""
    run = _runs.get(run_id)
    if run is None:
        return
    queue: asyncio.Queue = run["queue"]
    config = _default_config(req.config)
    selected = req.analysts
    completed: set[str] = set()

    from cli.stats_handler import StatsCallbackHandler
    stats = StatsCallbackHandler()

    await queue.put({
        "event": "run_started",
        "data": json.dumps({"run_id": run_id, "ticker": req.ticker,
                            "trade_date": req.trade_date,
                            "analysts": _analyst_meta(selected)}, ensure_ascii=False),
    })

    import time
    start_ts = time.time()
    last_stats_ts = 0.0

    async def _push_stats(force: bool = False):
        """Push a stats snapshot, throttled to ~every 2s (force on done/error)."""
        nonlocal last_stats_ts
        now = time.time()
        if not force and now - last_stats_ts < 2.0:
            return
        last_stats_ts = now
        s = stats.get_stats()
        await queue.put({
            "event": "stats",
            "data": json.dumps({
                "llm_calls": s["llm_calls"],
                "tool_calls": s["tool_calls"],
                "tokens_in": s["tokens_in"],
                "tokens_out": s["tokens_out"],
                "elapsed": round(now - start_ts, 1),
            }, ensure_ascii=False),
        })

    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        graph = TradingAgentsGraph(selected_analysts=selected, debug=True, config=config,
                                   callbacks=[stats])
        ticker = safe_ticker_component(req.ticker)

        # Start SFT recording for this analysis task.
        # Canary: prove this code path was reached.
        from tradingagents.agents.utils.sft_recorder import _canary
        _canary(f"web API _run_graph: about to start_sft_recording for {ticker} {req.trade_date}")
        start_sft_recording(ticker, str(req.trade_date))

        init_state, args, _ = graph.prepare_graph_run(ticker, req.trade_date)

        # astream with both modes: custom = token/tool events, updates = stage deltas.
        stream_args = {**args, "stream_mode": ["custom", "updates"]}
        # Seed last_state with the initial state so finalize_graph_run sees
        # company_of_interest / trade_date (updates mode only yields deltas).
        last_state: dict = dict(init_state) if init_state else {}
        async for mode, chunk in graph.graph.astream(init_state, **stream_args):
            if mode == "custom":
                await _emit_custom(queue, chunk)
                await _push_stats()
            elif mode == "updates":
                last_state = _merge_updates(last_state, chunk)
                for ev in detect_stage_events(chunk, completed, selected, ticker):
                    await queue.put({"event": "stage_done",
                                     "data": json.dumps(ev, ensure_ascii=False)})
                await _push_stats()

        signal = graph.finalize_graph_run(ticker, req.trade_date, last_state)

        # Auto-save Markdown report to ~/.tradingagents-biga/reports/
        from web.pdf_export import generate_markdown
        md_content = generate_markdown(last_state, ticker, req.trade_date, signal)
        reports_dir = Path.home() / ".tradingagents-biga" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        md_path = reports_dir / f"{ticker}_{req.trade_date}.md"
        md_path.write_text(md_content, encoding="utf-8")
        report_path = str(md_path)

        # Stash the completed report SEPARATELY from the run record, so it
        # survives the SSE teardown (the user downloads after the stream ends).
        _reports[run_id] = {
            "final_state": last_state,
            "ticker": ticker,
            "trade_date": req.trade_date,
            "signal": signal,
        }
        # Bound memory: keep only the most recent _MAX_REPORTS.
        if len(_reports) > _MAX_REPORTS:
            for stale in list(_reports.keys())[:-_MAX_REPORTS]:
                _reports.pop(stale, None)
        await _push_stats(force=True)
        s = stats.get_stats()
        await queue.put({
            "event": "done",
            "data": json.dumps({
                "run_id": run_id,
                "signal": signal,
                "elapsed": round(time.time() - start_ts, 1),
                "stats": s,
                "report_path": report_path,
            }, ensure_ascii=False),
        })
        graph.close_graph_run()
    except asyncio.CancelledError:
        # User hit Stop. Don't treat as an error — close the graph cleanly and
        # push a done(stopped) event so the frontend can settle (it also closes
        # the EventSource locally, but this makes the termination explicit).
        try:
            graph.close_graph_run()
        except Exception:
            pass
        await queue.put({
            "event": "done",
            "data": json.dumps({"run_id": run_id, "signal": "已停止",
                                "elapsed": round(time.time() - start_ts, 1),
                                "stopped": True}, ensure_ascii=False),
        })
        raise  # propagate so the task is marked cancelled
    except Exception as e:
        import traceback
        await queue.put({"event": "error",
                         "data": json.dumps({"message": str(e),
                                             "traceback": traceback.format_exc()},
                                            ensure_ascii=False)})
    finally:
        stop_sft_recording()
        await queue.put({"event": "_close", "data": ""})  # sentinel


async def _emit_custom(queue: asyncio.Queue, ev: dict) -> None:
    """Translate a run_react_loop custom event into an SSE event."""
    etype = ev.get("type")
    if etype == "token":
        await queue.put({"event": "token",
                         "data": json.dumps({"agent_id": ev.get("agent_id"),
                                             "text": ev.get("text", "")}, ensure_ascii=False)})
    elif etype in ("tool_call", "tool_start", "tool_end"):
        await queue.put({"event": "tool",
                         "data": json.dumps(ev, ensure_ascii=False)})
    elif etype == "report_done":
        # Already covered by the updates-driven stage_done, but emit a cheap
        # marker too so the frontend can flip the card even if the update lags.
        await queue.put({"event": "stage_done",
                         "data": json.dumps({"agent_id": ev.get("agent_id")},
                                            ensure_ascii=False)})


def _merge_updates(state: dict, updates: dict) -> dict:
    """Accumulate updates-mode chunks into a running state snapshot."""
    merged = dict(state)
    if updates and all(isinstance(v, dict) for v in updates.values()):
        for v in updates.values():
            merged.update(v)
    else:
        merged.update(updates or {})
    return merged


@app.get("/api/stream/{run_id}")
async def stream(run_id: str):
    """SSE stream for a run: yields events until the run closes."""
    run = _runs.get(run_id)
    if run is None:
        return EventSourceResponse(
            iter([{"event": "error", "data": json.dumps({"message": "unknown run_id"})}]))
    queue: asyncio.Queue = run["queue"]

    async def event_gen():
        try:
            while True:
                item = await queue.get()
                if item.get("event") == "_close":
                    break
                yield item
        finally:
            _runs.pop(run_id, None)

    return EventSourceResponse(event_gen())


@app.post("/api/stop/{run_id}")
async def stop(run_id: str) -> dict:
    """Cancel an in-flight run so the user can stop early (saves tokens/time).

    Cancels the asyncio task running the graph and awaits its termination
    (bounded by a timeout) so that by the time we return, the old run has
    actually stopped — preventing a brief window where the old and new runs
    overlap when the user immediately re-starts.
    """
    run = _runs.get(run_id)
    if run is None:
        return {"stopped": False, "reason": "unknown run_id"}
    task: asyncio.Task = run.get("task")
    if task is not None and not task.done():
        task.cancel()
        try:
            # Wait for the cancel to propagate (graph stops, close_graph_run
            # runs). 5s cap so a wedged node can't hold the stop request forever.
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    return {"stopped": True}


@app.get("/api/report/{run_id}/md")
def report_md(run_id: str):
    """Download the full analysis as Markdown."""
    from fastapi.responses import PlainTextResponse
    from web.pdf_export import generate_markdown
    rep = _reports.get(run_id)
    if rep is None:
        return PlainTextResponse("报告尚未生成或已过期", status_code=404)
    md = generate_markdown(rep["final_state"], rep["ticker"], rep["trade_date"], rep["signal"])
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{rep["ticker"]}_{rep["trade_date"]}.md"'})


@app.get("/api/report/{run_id}/pdf")
def report_pdf(run_id: str):
    """Download the full analysis as PDF."""
    from fastapi.responses import Response
    from web.pdf_export import generate_pdf
    rep = _reports.get(run_id)
    if rep is None:
        return Response("报告尚未生成或已过期", status_code=404)
    pdf_bytes = generate_pdf(rep["final_state"], rep["ticker"], rep["trade_date"], rep["signal"])
    return Response(pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{rep["ticker"]}_{rep["trade_date"]}.pdf"'})

_REPORTS_DIR = str(Path.home() / ".tradingagents-biga" / "reports")

@app.post("/api/report/open-folder")
def open_reports_folder() -> dict:
    """Open the reports directory in the OS file manager."""
    try:
        if platform.system() == "Windows":
            os.startfile(_REPORTS_DIR)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", _REPORTS_DIR])
        else:
            subprocess.Popen(["xdg-open", _REPORTS_DIR])
        return {"opened": _REPORTS_DIR}
    except Exception as e:
        return {"error": str(e), "path": _REPORTS_DIR}


# In production, serve the built TS frontend from the same origin.
@app.on_event("startup")
def _mount_static() -> None:
    import os
    dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
    if os.path.isdir(dist):
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
