import { useState } from "react";
import type { LlmConfig, ProviderInfo } from "../api/types";
import { ConfigPanel } from "./ConfigPanel";

interface Props {
  config: LlmConfig;
  onChange: (c: LlmConfig) => void;
  providers: ProviderInfo[];
  defaultProvider: string | null;
  onReload: () => void;
  disabled?: boolean;
}

/**
 * Collapsible left rail for the LLM model config.
 *
 * Collapsed: a slim card showing the active provider + model + a gear icon
 * (so the top of the page isn't dominated by config when you just want to
 * run an analysis). Click to expand into the full ConfigPanel.
 *
 * Expanded: the full config form; click the header again (or ✕) to collapse.
 */
export function Sidebar({ config, onChange, providers, defaultProvider, onReload, disabled }: Props) {
  const [expanded, setExpanded] = useState(false);
  const current = providers.find((p) => p.key === config.llm_provider);

  return (
    <aside className={`sidebar ${expanded ? "expanded" : "collapsed"}`}>
      <div className="sidebar-header" onClick={() => !disabled && setExpanded((e) => !e)}>
        <span className="sidebar-title">⚙️ 模型配置</span>
        {expanded ? (
          <span className="sidebar-toggle">✕</span>
        ) : (
          <span className="sidebar-toggle">▸</span>
        )}
      </div>

      {expanded ? (
        <div className="sidebar-body">
          <ConfigPanel
            value={config}
            onChange={onChange}
            disabled={disabled}
            providers={providers}
            defaultProvider={defaultProvider}
            onReload={onReload}
          />
        </div>
      ) : (
        <div className="sidebar-summary" onClick={() => !disabled && setExpanded(true)}>
          <div className="summary-row">
            <span className="summary-label">供应商</span>
            <span className="summary-value">{current?.label ?? config.llm_provider}</span>
          </div>
          <div className="summary-row">
            <span className="summary-label">快速</span>
            <span className="summary-value ellipsis">{config.quick_think_llm || "—"}</span>
          </div>
          <div className="summary-row">
            <span className="summary-label">深度</span>
            <span className="summary-value ellipsis">{config.deep_think_llm || "—"}</span>
          </div>
          <div className="summary-row">
            <span className="summary-label">Key</span>
            <span className="summary-value">{current?.has_key ? "✓ 已设置" : "未设置"}</span>
          </div>
          <div className="summary-hint">点击展开配置</div>
        </div>
      )}
    </aside>
  );
}
