import type { PostStage } from "../api/types";

interface Props {
  stats: { llm_calls: number; tool_calls: number; tokens_in: number; tokens_out: number; elapsed: number };
  postStages: PostStage[];
  signal: string | null;
  runId: string | null;
}

/**
 * Always-visible status panel — sits BELOW the model-config Sidebar.
 *
 * Live stats (elapsed/LLM/tool/tokens) + downstream progress (with an "active"
 * pulse so the user always sees what's running — fixes the "all green, looks
 * stuck" gap during PM judging) + report downloads once done. Never collapsed:
 * the whole point is the user sees status without interacting with config.
 */
export function StatusPanel({ stats, postStages, signal, runId }: Props) {
  // Always rendered — even before a run starts the framework is visible (stats
  // at 0, stages all ○ and not flashing). The "active" pulse only lights when
  // a run is in progress AND the stage's predecessors are done.
  return (
    <aside className="status-panel">
      <div className="rail-section">
        <div className="rail-title">实时统计</div>
        <div className="stat-grid">
          <div className="stat-cell"><span className="stat-k">⏱ 用时</span><span className="stat-v">{stats.elapsed}s</span></div>
          <div className="stat-cell"><span className="stat-k">🧠 LLM</span><span className="stat-v">{stats.llm_calls}</span></div>
          <div className="stat-cell"><span className="stat-k">⚡ 工具</span><span className="stat-v">{stats.tool_calls}</span></div>
          <div className="stat-cell"><span className="stat-k">↓ 入 tok</span><span className="stat-v">{stats.tokens_in.toLocaleString()}</span></div>
          <div className="stat-cell"><span className="stat-k">↑ 出 tok</span><span className="stat-v">{stats.tokens_out.toLocaleString()}</span></div>
          {signal && <div className="stat-cell signal-cell"><span className="stat-k">信号</span><span className="stat-v">{signal}</span></div>}
        </div>
      </div>

      <div className="rail-section">
        <div className="rail-title">下游进度</div>
        <div className="stage-list">
          {postStages.map((s) => (
            <div key={s.id} className={`stage-row ${s.done ? "done" : s.active ? "active" : ""}`}>
              <span className="stage-icon">{s.icon}</span>
              <span className="stage-name">{s.name}</span>
              <span className="stage-mark">{s.done ? "✓" : s.active ? "⏳" : "○"}</span>
            </div>
          ))}
        </div>
      </div>

      {signal && runId && (
        <div className="status-downloads">
          <a className="btn-download" href={`/api/report/${runId}/md`} target="_blank" rel="noreferrer">📄 Markdown</a>
          <a className="btn-download" href={`/api/report/${runId}/pdf`} target="_blank" rel="noreferrer">📕 PDF</a>
        </div>
      )}
    </aside>
  );
}
