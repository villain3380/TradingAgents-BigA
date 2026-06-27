#!/usr/bin/env python3
"""SFT JSONL Data Viewer — standalone web tool for human review of training data.

Usage::

    python data/data_viewer.py
    # Open http://localhost:8765 in your browser

Zero dependencies beyond Python stdlib.  Reads JSONL files from
``~/.tradingagents/sft/`` and renders each agent's conversation as a
chat-like view with markdown formatting, syntax-highlighted tool calls,
and one-click quality ratings (good / bad / skip).  Review decisions are
persisted to ``~/.tradingagents/sft/_reviews.json``.

Keyboard shortcuts:
    ← / →      prev / next record
    g          mark good
    b          mark bad
    s          mark skip
    f          focus search
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

# ── config ───────────────────────────────────────────────────────────────────

HOST = "127.0.0.1"
PORT = 8765
SFT_DIR = Path.home() / ".tradingagents" / "sft"
REVIEWS_FILE = SFT_DIR / "_reviews.json"

# ── helpers ──────────────────────────────────────────────────────────────────

def _json_reply(handler, data: Any, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _load_reviews() -> dict[str, dict[str, str]]:
    """Return {file_stem: {agent_id: rating}}."""
    if REVIEWS_FILE.exists():
        try:
            return json.loads(REVIEWS_FILE.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_reviews(reviews: dict) -> None:
    REVIEWS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REVIEWS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(reviews, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(REVIEWS_FILE)


# ── HTTP handler ─────────────────────────────────────────────────────────────

class SFTViewerHandler(SimpleHTTPRequestHandler):
    """Serves the SFT viewer SPA and a small JSON API."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        # ── static / HTML page ──────────────────────────────────────────
        if path == "/" or path == "/index.html":
            self._serve_html()
            return

        # ── API: list files ─────────────────────────────────────────────
        if path == "/api/files":
            files = sorted(SFT_DIR.glob("*.jsonl"), key=os.path.getmtime, reverse=True)
            result = []
            for f in files:
                stat = f.stat()
                # quick peek: count records + agents
                agents: list[str] = []
                count = 0
                try:
                    for line in f.read_text("utf-8").strip().splitlines():
                        if not line.strip():
                            continue
                        rec = json.loads(line)
                        agents.append(rec.get("agent_id", "?"))
                        count += 1
                except Exception:
                    pass
                # Parse ticker + date from filename: {ticker}_{date}_{ts}.jsonl
                stem = f.stem
                parts = stem.split("_")
                ticker = parts[0] if parts else "?"
                date_str = f"{parts[1]}" if len(parts) > 1 else "?"
                result.append({
                    "name": f.name,
                    "path": str(f),
                    "ticker": ticker,
                    "date": date_str,
                    "records": count,
                    "agents": agents,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
            _json_reply(self, result)
            return

        # ── API: get one file's contents ────────────────────────────────
        if path == "/api/file":
            file_path = qs.get("path", [None])[0]
            if not file_path:
                _json_reply(self, {"error": "missing ?path="}, 400)
                return
            fp = Path(file_path)
            if not fp.exists() or not str(fp.resolve()).startswith(str(SFT_DIR.resolve())):
                _json_reply(self, {"error": "file not found or outside sft dir"}, 404)
                return
            records = []
            for line in fp.read_text("utf-8").strip().splitlines():
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            _json_reply(self, records)
            return

        # ── API: get reviews ────────────────────────────────────────────
        if path == "/api/reviews":
            _json_reply(self, _load_reviews())
            return

        # ── fallback: 404 ───────────────────────────────────────────────
        self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            _json_reply(self, {"error": "invalid json"}, 400)
            return

        if self.path.rstrip("/") == "/api/reviews":
            # data: {file_stem: {agent_id: rating}}
            _save_reviews(data)
            _json_reply(self, {"ok": True})
            return

        self.send_error(404, "Not Found")

    def log_message(self, format, *args):
        """Suppress access logs for cleaner output."""
        if "/api/" in str(args[0]):
            print(f"  {args[0]}")
        # suppress static file logs

    # ── HTML page ────────────────────────────────────────────────────────
    def _serve_html(self) -> None:
        html = _HTML_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


# ── HTML / CSS / JS (single page app) ────────────────────────────────────────

_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SFT Data Viewer</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
:root {
  --bg: #1a1a2e; --surface: #16213e; --card: #0f3460;
  --text: #e0e0e0; --muted: #8892b0; --accent: #e94560;
  --good: #2ecc71; --bad: #e74c3c; --skip: #f39c12;
  --border: #2a2a4a;
  --system-bg: #1a1a2e; --user-bg: #162447; --asst-bg: #0f3460; --tool-bg: #1a2639;
}
* { box-sizing:border-box; margin:0; padding:0 }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background:var(--bg); color:var(--text); height:100vh; display:flex; flex-direction:column }
header { background:var(--surface); padding:8px 16px; display:flex; align-items:center;
         gap:12px; border-bottom:1px solid var(--border); flex-shrink:0 }
header h1 { font-size:18px; font-weight:600; white-space:nowrap }
header .stats { font-size:12px; color:var(--muted); margin-left:auto }
#layout { display:flex; flex:1; overflow:hidden }
#sidebar { width:280px; flex-shrink:0; background:var(--surface); border-right:1px solid var(--border);
           display:flex; flex-direction:column; overflow:hidden }
#sidebar .section { padding:10px 12px; border-bottom:1px solid var(--border) }
#sidebar .section h3 { font-size:12px; text-transform:uppercase; color:var(--muted); margin-bottom:8px }
#file-list { flex:1; overflow-y:auto; padding:4px 0 }
#file-list .file { padding:8px 12px; cursor:pointer; font-size:13px; border-left:3px solid transparent;
    transition: background .15s }
#file-list .file:hover { background:rgba(255,255,255,.04) }
#file-list .file.active { border-left-color:var(--accent); background:rgba(233,69,96,.1) }
#file-list .file .name { font-weight:500 }
#file-list .file .meta { font-size:11px; color:var(--muted); margin-top:2px }
#filter-box { width:100%; padding:6px 8px; font-size:12px; background:var(--bg); color:var(--text);
              border:1px solid var(--border); border-radius:4px; margin-bottom:8px }
#filter-box::placeholder { color:var(--muted) }
.tag { display:inline-block; padding:1px 6px; border-radius:3px; font-size:11px; margin:1px 2px }
.tag-good { background:rgba(46,204,113,.2); color:var(--good) }
.tag-bad  { background:rgba(231,76,60,.2);  color:var(--bad) }
.tag-skip { background:rgba(243,156,18,.2); color:var(--skip) }
#main { flex:1; overflow-y:auto; padding:16px 20px }
#main .empty { text-align:center; color:var(--muted); margin-top:80px; font-size:15px }
.record { margin-bottom:24px; border:1px solid var(--border); border-radius:8px; overflow:hidden }
.record-header { background:var(--card); padding:10px 14px; display:flex; align-items:center;
    gap:10px; flex-wrap:wrap; font-size:13px }
.record-header .agent-id { font-weight:600; color:var(--accent) }
.record-header .agent-role { color:var(--muted) }
.record-header .tools { margin-left:auto; display:flex; gap:4px; flex-wrap:wrap }
.record-header .tool-chip { font-size:10px; padding:2px 6px; border-radius:3px;
    background:rgba(255,255,255,.06); color:var(--muted) }
.msg { padding:12px 14px; border-bottom:1px solid var(--border); position:relative }
.msg:last-child { border-bottom:none }
.msg-system { background:var(--system-bg); font-size:12px; color:var(--muted); max-height:120px;
    overflow-y:auto; cursor:pointer }
.msg-system.expanded { max-height:none }
.msg-system::before { content:"📋 system"; font-size:10px; color:var(--muted);
    display:block; margin-bottom:4px }
.msg-user { background:var(--user-bg) }
.msg-user::before { content:"👤 user"; font-size:10px; color:#5dade2; display:block; margin-bottom:4px }
.msg-tool { background:var(--tool-bg) }
.msg-tool summary { font-size:10px; color:var(--muted); cursor:pointer; margin-bottom:4px;
    user-select:none }
.msg-tool summary .tid { color:var(--accent); font-family:monospace }
.msg-tool pre { font-size:11px; max-height:200px; overflow:auto; white-space:pre-wrap;
    word-break:break-all; margin-top:4px; color:var(--muted) }
.msg-assistant { background:var(--asst-bg) }
.msg-assistant.no-tools::before { content:"📝 assistant"; font-size:10px; color:var(--good);
    display:block; margin-bottom:4px }
.msg-assistant.has-tools::before { content:"🔧 assistant (tool_calls)"; font-size:10px;
    color:#f39c12; display:block; margin-bottom:4px }
.msg-assistant .tc-block { background:rgba(0,0,0,.2); border-radius:4px; padding:6px 8px;
    margin:6px 0; font-size:12px }
.msg-assistant .tc-block .fn { color:var(--accent); font-weight:600 }
.msg-assistant .tc-block .args { color:var(--muted); font-family:monospace; font-size:11px }
.msg-content { line-height:1.6; word-break:break-word }
.msg-content p { margin:4px 0 }
.msg-content table { border-collapse:collapse; font-size:12px; width:100%; margin:8px 0 }
.msg-content th, .msg-content td { border:1px solid var(--border); padding:4px 8px; text-align:left }
.msg-content th { background:rgba(255,255,255,.05) }
.msg-content code { background:rgba(255,255,255,.08); padding:1px 4px; border-radius:2px;
    font-size:11px }
.msg-content pre { background:rgba(0,0,0,.3); padding:8px 12px; border-radius:4px;
    overflow-x:auto; font-size:11px }
.msg-content pre code { background:none; padding:0 }
.record-footer { background:var(--card); padding:8px 14px; display:flex; gap:8px; align-items:center }
.record-footer button { padding:4px 14px; border:1px solid var(--border); border-radius:4px;
    cursor:pointer; font-size:12px; background:var(--surface); color:var(--text); transition:all .15s }
.record-footer button:hover { filter:brightness(1.3) }
.record-footer button.good.active { background:var(--good); border-color:var(--good); color:#000 }
.record-footer button.bad.active  { background:var(--bad);  border-color:var(--bad);  color:#fff }
.record-footer button.skip.active { background:var(--skip); border-color:var(--skip); color:#000 }
.record-footer .review-note { font-size:11px; color:var(--muted); margin-left:8px }
#toast { position:fixed; bottom:20px; right:20px; background:var(--card); color:var(--text);
    padding:8px 16px; border-radius:6px; font-size:13px; opacity:0; transition:opacity .3s;
    pointer-events:none; z-index:999 }
#toast.show { opacity:1 }
kbd { background:rgba(255,255,255,.1); padding:1px 5px; border-radius:3px; font-size:10px;
    border:1px solid var(--border) }
</style>
</head>
<body>

<header>
  <h1>📊 SFT Data Viewer</h1>
  <span style="font-size:12px;color:var(--muted)">~/.tradingagents/sft/</span>
  <span class="stats" id="stats"></span>
</header>

<div id="layout">
  <nav id="sidebar">
    <div class="section">
      <h3>🔍 Filter</h3>
      <input id="filter-box" type="text" placeholder="agent:market status:ok has:tools text:关键词..." oninput="applyFilter()">
    </div>
    <div class="section" style="font-size:11px;color:var(--muted)">
      <kbd>←</kbd><kbd>→</kbd> nav &nbsp; <kbd>g</kbd> good &nbsp; <kbd>b</kbd> bad &nbsp; <kbd>s</kbd> skip &nbsp; <kbd>f</kbd> filter
    </div>
    <div id="file-list"></div>
  </nav>
  <main id="main">
    <div class="empty">📂 Select a JSONL file from the sidebar to start reviewing</div>
  </main>
</div>
<div id="toast"></div>

<script>
// ── state ─────────────────────────────────────────────────────────────────
let STATE = {
  files: [],
  records: [],        // all records in current file
  filtered: [],       // after filter applied
  currentIdx: 0,
  currentFile: null,
  reviews: {},        // {file_stem: {agent_id: rating}}
};
let toastTimer = null;

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2000);
}

// ── API ────────────────────────────────────────────────────────────────────
async function api(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

// ── load files ─────────────────────────────────────────────────────────────
async function loadFiles() {
  STATE.files = await api('/api/files');
  STATE.reviews = await api('/api/reviews');
  renderSidebar();
}

function renderSidebar() {
  const el = document.getElementById('file-list');
  const filterVal = (document.getElementById('filter-box').value || '').toLowerCase();
  let files = STATE.files;
  if (filterVal) {
    files = files.filter(f =>
      f.name.toLowerCase().includes(filterVal) ||
      f.ticker.includes(filterVal) ||
      f.date.includes(filterVal)
    );
  }
  el.innerHTML = files.map(f => {
    const stem = f.name.replace('.jsonl','');
    const revs = STATE.reviews[stem] || {};
    const good = Object.values(revs).filter(v=>v==='good').length;
    const bad  = Object.values(revs).filter(v=>v==='bad').length;
    let tags = '';
    if (good) tags += `<span class="tag tag-good">✓${good}</span>`;
    if (bad)  tags += `<span class="tag tag-bad">✗${bad}</span>`;
    const active = STATE.currentFile === f.name ? ' active' : '';
    return `<div class="file${active}" onclick="selectFile('${f.name}')" title="${f.path}">
      <div class="name">📄 ${f.ticker} <span style="color:var(--muted)">${f.date}</span> ${tags}</div>
      <div class="meta">${f.records} agents · ${f.size_kb} KB · ${f.agents.filter((v,i,a)=>a.indexOf(v)===i).join(', ')}</div>
    </div>`;
  }).join('');
}

// ── select file ────────────────────────────────────────────────────────────
async function selectFile(fname) {
  STATE.currentFile = fname;
  STATE.currentIdx = 0;
  const f = STATE.files.find(x => x.name === fname);
  if (!f) return;
  STATE.records = await api('/api/file?path=' + encodeURIComponent(f.path));
  applyFilter();
  renderSidebar();
}

function applyFilter() {
  const raw = (document.getElementById('filter-box').value || '').trim();
  let records = STATE.records;
  if (raw) {
    const parts = raw.split(/\s+/);
    for (const p of parts) {
      if (p.startsWith('agent:')) {
        const v = p.slice(6).toLowerCase();
        records = records.filter(r => r.agent_id.toLowerCase().includes(v));
      } else if (p.startsWith('ticker:')) {
        const v = p.slice(7);
        records = records.filter(r => (r.task.ticker||'').includes(v));
      } else if (p === 'has:tools') {
        records = records.filter(r => r.tools && r.tools.length > 0);
      } else if (p === 'no:tools') {
        records = records.filter(r => !r.tools || r.tools.length === 0);
      } else if (p.startsWith('text:')) {
        const v = p.slice(5).toLowerCase();
        records = records.filter(r => JSON.stringify(r.messages).toLowerCase().includes(v));
      } else if (p.startsWith('role:')) {
        const v = p.slice(5);
        records = records.filter(r => r.agent_role.includes(v));
      } else if (p.startsWith('status:')) {
        const v = p.slice(7).toLowerCase();
        records = records.filter(r => (r.status || 'ok').toLowerCase() === v);
      } else {
        // free-text search across agent_id + role + messages
        const v = p.toLowerCase();
        records = records.filter(r =>
          r.agent_id.toLowerCase().includes(v) ||
          r.agent_role.includes(v) ||
          JSON.stringify(r.messages).toLowerCase().includes(v)
        );
      }
    }
  }
  STATE.filtered = records;
  STATE.currentIdx = Math.min(STATE.currentIdx, Math.max(0, records.length - 1));
  renderMain();
  updateStats();
}

function updateStats() {
  const el = document.getElementById('stats');
  if (!STATE.currentFile) { el.textContent = ''; return }
  const stem = STATE.currentFile.replace('.jsonl','');
  const revs = STATE.reviews[stem] || {};
  const rated = Object.keys(revs).length;
  el.textContent = `${STATE.filtered.length} records · ${rated} rated · ${STATE.currentIdx+1}/${STATE.filtered.length}`;
}

// ── render main ────────────────────────────────────────────────────────────
function renderMain() {
  const main = document.getElementById('main');
  if (!STATE.currentFile || STATE.filtered.length === 0) {
    main.innerHTML = '<div class="empty">📂 No records match the filter</div>';
    return;
  }

  const idx = STATE.currentIdx;
  const rec = STATE.filtered[idx];
  const stem = STATE.currentFile.replace('.jsonl','');
  const revs = STATE.reviews[stem] || {};
  const rating = revs[rec.agent_id] || '';

  const messagesHtml = (rec.messages || []).map((m, i) => {
    const role = m.role || 'unknown';
    let cls = '', label = '', body = '';

    if (role === 'system') {
      cls = 'msg-system';
      const txt = escHtml(m.content || '');
      body = txt.length > 400
        ? `<div onclick="this.parentElement.classList.toggle('expanded')">${txt.slice(0,400)}… <em>(click to expand, ${txt.length} chars)</em></div>`
        : `<div>${txt}</div>`;
    } else if (role === 'user') {
      cls = 'msg-user';
      body = `<div class="msg-content">${escHtml(m.content || '(empty)')}</div>`;
    } else if (role === 'tool') {
      cls = 'msg-tool';
      const tid = (m.tool_call_id || '?').slice(0,24);
      const tname = m.name || '';
      const nameTag = tname ? `<span class="tid">${escHtml(tname)}</span> · ` : '';
      body = `<details><summary>🔗 ${nameTag}tool_call_id: <span class="tid">${escHtml(tid)}…</span></summary>
        <pre>${escHtml(m.content || '')}</pre></details>`;
    } else if (role === 'assistant') {
      const tcs = m.tool_calls;
      if (tcs && tcs.length > 0) {
        cls = 'msg-assistant has-tools';
        // OpenAI tool-calling shape: {type:"function", id, function:{name, arguments}}
        let tcHtml = tcs.map(tc => {
          const fn = tc.function || {};
          const fnName = fn.name || tc.name || '?';
          const fnArgs = fn.arguments != null ? fn.arguments : tc.args;
          const argsStr = typeof fnArgs === 'string' ? fnArgs : JSON.stringify(fnArgs || {}, null, 2);
          return `<div class="tc-block">
            <span class="fn">⚡ ${escHtml(fnName)}</span>
            <div class="args">${escHtml(argsStr)}</div>
          </div>`;
        }).join('');
        // content is null on a pure tool-call turn; render only if present
        body = tcHtml + (m.content ? `<div class="msg-content">${renderMd(m.content)}</div>` : '');
      } else {
        cls = 'msg-assistant no-tools';
        body = `<div class="msg-content">${renderMd(m.content || '')}</div>`;
      }
    }
    return `<div class="msg ${cls}">${body}</div>`;
  }).join('');

  // tools is the OpenAI schema list [{type:"function",function:{name,...}}] (or [] for no-tool nodes)
  const toolName = t => (t && t.function && t.function.name) || (typeof t === 'string' ? t : '?');
  const toolsHtml = (rec.tools || []).map(t => `<span class="tool-chip" title="${escHtml(JSON.stringify(t))}">⚡${escHtml(toolName(t))}</span>`).join('');

  // status badge — surfaces P7 contamination so reviewers can spot non-ok records
  const status = rec.status || 'ok';
  const statusLabel = {ok:'✓ ok', incomplete:'⚠ incomplete', degraded:'✗ degraded'}[status] || status;
  const statusCls = `tag-${status==='ok'?'good':status==='degraded'?'bad':'skip'}`;
  const reason = rec.degradation_reason ? ` · ${escHtml(rec.degradation_reason)}` : '';
  const statusHtml = `<span class="tag ${statusCls}" title="训练前请过滤 status==ok">${statusLabel}${reason}</span>`;

  main.innerHTML = `
    <div class="record">
      <div class="record-header">
        <span class="agent-id">${escHtml(rec.agent_id)}</span>
        <span class="agent-role">${escHtml(rec.agent_role)}</span>
        ${statusHtml}
        <span style="font-size:11px;color:var(--muted)">📅 ${escHtml(rec.task?.trade_date||'?')} · 🏷 ${escHtml(rec.task?.ticker||'?')}</span>
        <span class="tools">${toolsHtml}</span>
      </div>
      ${messagesHtml}
      <div class="record-footer">
        <button ${idx===0?'disabled':''} onclick="prevRecord()" title="上一页 ←">◀ Prev</button>
        <span style="font-size:12px">#${idx+1}/${STATE.filtered.length}</span>
        <button ${idx>=STATE.filtered.length-1?'disabled':''} onclick="nextRecord()" title="下一页 →">Next ▶</button>
        <span style="width:12px"></span>
        <button class="good${rating==='good'?' active':''}" onclick="rate('good')">✓ Good</button>
        <button class="bad${rating==='bad'?' active':''}" onclick="rate('bad')">✗ Bad</button>
        <button class="skip${rating==='skip'?' active':''}" onclick="rate('skip')">→ Skip</button>
        ${rating ? `<span class="review-note">当前: ${rating}</span>` : ''}
        <span style="margin-left:auto;font-size:11px;color:var(--muted)">
          ${rec.messages?.length || 0} messages
        </span>
      </div>
    </div>`;
}

// ── helpers ────────────────────────────────────────────────────────────────
function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function renderMd(text) {
  if (!text) return '';
  if (typeof marked !== 'undefined') {
    try {
      return marked.parse(text);
    } catch(e) { /* fall through */ }
  }
  return '<pre>' + escHtml(text) + '</pre>';
}

// ── rating ─────────────────────────────────────────────────────────────────
function prevRecord() {
  if (STATE.currentIdx > 0) {
    STATE.currentIdx--;
    renderMain();
    updateStats();
    return true;
  }
  return false;
}

function nextRecord() {
  if (STATE.currentIdx < STATE.filtered.length - 1) {
    STATE.currentIdx++;
    renderMain();
    updateStats();
    return true;
  }
  return false;
}

async function rate(val) {
  const stem = STATE.currentFile.replace('.jsonl','');
  const rec = STATE.filtered[STATE.currentIdx];
  if (!rec) return;
  if (!STATE.reviews[stem]) STATE.reviews[stem] = {};
  STATE.reviews[stem][rec.agent_id] = val;
  await fetch('/api/reviews', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(STATE.reviews)
  });
  const label = val === 'good' ? '✓ Good' : val === 'bad' ? '✗ Bad' : '→ Skip';
  if (nextRecord()) {
    renderSidebar();
    toast(`已标记为 ${label}，自动跳转下一页`);
  } else {
    renderMain();
    updateStats();
    renderSidebar();
    toast(`已标记为 ${label}（已是最后一条）`);
  }
}

// ── keyboard ───────────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return; // don't intercept filter box
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
    e.preventDefault();
    if (STATE.currentIdx < STATE.filtered.length - 1) {
      STATE.currentIdx++;
      renderMain(); updateStats();
    }
  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
    e.preventDefault();
    if (STATE.currentIdx > 0) {
      STATE.currentIdx--;
      renderMain(); updateStats();
    }
  } else if (e.key === 'g') { rate('good');
  } else if (e.key === 'b') { rate('bad');
  } else if (e.key === 's') { rate('skip');
  } else if (e.key === 'f') {
    e.preventDefault();
    document.getElementById('filter-box').focus();
  }
});

// ── init ───────────────────────────────────────────────────────────────────
loadFiles();

// Refresh file list when filter box changes (sidebar file search)
document.getElementById('filter-box').addEventListener('input', () => {
  // If a file IS loaded, apply record-level filter. Otherwise filter sidebar.
  if (STATE.currentFile) {
    applyFilter();
  }
  renderSidebar();
});
</script>
</body>
</html>"""


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    SFT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"SFT Data Viewer")
    print(f"  SFT dir : {SFT_DIR}")
    print(f"  Open    : http://{HOST}:{PORT}")
    print(f"  Press Ctrl+C to stop.\n")

    server = HTTPServer((HOST, PORT), SFTViewerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
