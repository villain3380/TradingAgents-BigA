import type { RunState, PostStage } from "../api/types";

interface Props {
  state: RunState;
  runId: string | null;
}

/**
 * Sticky right rail: live stats (elapsed/LLM/tool/tokens) + downstream stage
 * progress + report downloads. Always visible without scrolling, mirroring the
 * left config sidebar so the analyst card grid in the middle is the only thing
 * that scrolls.
 */
export function RightRail({ state, runId }: Props) {
  const st = state.stats;
  const show = state.running || state.signal || state.cards.length > 0;
  if (!show) return null;

  return (
    <aside className="right-rail">
      {state.running || state.signal ? (
        <div className="rail-section">
          <div className="rail-title">实时统计</div>
          <div className="stat-grid">
            <div className="stat-cell"><span className="stat-k">⏱ 用时</span><span className="stat-v">{st.elapsed}s</span></div>
            <div className="stat-cell"><span className="stat-k">🧠 LLM</span><span className="stat-v">{st.llm_calls}</span></div>
            <div className="stat-cell"><span className="stat-k">⚡ 工具</span><span className="stat-v">{st.tool_calls}</span></div>
            <div className="stat-cell"><span className="stat-k">↓ 入 tok</span><span className="stat-v">{st.tokens_in.toLocaleString()}</span></div>
            <div className="stat-cell"><span className="stat-k">↑ 出 tok</span><span className="stat-v">{st.tokens_out.toLocaleString()}</span></div>
            {state.signal && <div className="stat-cell signal-cell"><span className="stat-k">信号</span><span className="stat-v">{state.signal}</span></div>}
          </div>
        </div>
      ) : null}

      {state.postStages.length > 0 && (
        <div className="rail-section">
          <div className="rail-title">下游进度</div>
          <div className="stage-list">
            {state.postStages.map((s: PostStage) => (
              <div key={s.id} className={`stage-row ${s.done ? "done" : ""}`}>
                <span className="stage-icon">{s.icon}</span>
                <span className="stage-name">{s.name}</span>
                <span className="stage-mark">{s.done ? "✓" : "○"}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {state.signal && runId && (
        <div className="rail-section">
          <div className="rail-title">下载报告</div>
          <a className="btn-download" href={`/api/report/${runId}/md`} target="_blank" rel="noreferrer">
            📄 Markdown
          </a>
          <a className="btn-download" href={`/api/report/${runId}/pdf`} target="_blank" rel="noreferrer">
            📕 PDF
          </a>
        </div>
      )}
    </aside>
  );
}
