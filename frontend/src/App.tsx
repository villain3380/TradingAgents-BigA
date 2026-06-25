import { useEffect, useState, useCallback } from "react";
import { useAnalysisStream } from "./hooks/useAnalysisStream";
import { listAnalysts, listProviders } from "./api/client";
import type { AnalystMeta, LlmConfig, ProviderInfo } from "./api/types";
import { Controls } from "./components/Controls";
import { Sidebar } from "./components/Sidebar";
import { StatusPanel } from "./components/StatusPanel";
import { RightRail } from "./components/RightRail";
import { AnalystGrid } from "./components/AnalystGrid";
import { CardModal } from "./components/CardModal";

const FALLBACK_CONFIG: LlmConfig = {
  llm_provider: "minimax",
  quick_think_llm: "MiniMax-M2.7-highspeed",
  deep_think_llm: "MiniMax-M2.7",
  backend_url: null,
};

export default function App() {
  const [analysts, setAnalysts] = useState<AnalystMeta[]>([]);
  const [llmConfig, setLlmConfig] = useState<LlmConfig>(FALLBACK_CONFIG);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [defaultProvider, setDefaultProvider] = useState<string | null>(null);
  const { state, expandedKey, setExpandedKey, start, stop, runId } = useAnalysisStream();

  const reloadProviders = useCallback(() => {
    return listProviders().then((resp) => {
      setProviders(resp.providers);
      setDefaultProvider(resp.default_provider);
      return resp;
    });
  }, []);

  useEffect(() => {
    listAnalysts().then(setAnalysts).catch(() => {});
    reloadProviders().then((resp) => {
      const dp = resp.default_provider;
      if (!dp) return;
      const p = resp.providers.find((x) => x.key === dp);
      if (!p) return;
      setLlmConfig({
        llm_provider: dp,
        quick_think_llm: p.selected.quick_think_llm || FALLBACK_CONFIG.quick_think_llm,
        deep_think_llm: p.selected.deep_think_llm || FALLBACK_CONFIG.deep_think_llm,
        backend_url: p.selected.backend_url || null,
      });
    }).catch(() => {});
  }, [reloadProviders]);

  return (
    <div className="app-layout">
      <div className="left-rail">
        <Sidebar
          config={llmConfig}
          onChange={setLlmConfig}
          providers={providers}
          defaultProvider={defaultProvider}
          onReload={reloadProviders}
          disabled={state.running}
        />
        <StatusPanel
          stats={state.stats}
          postStages={state.postStages}
          signal={state.signal}
          runId={runId}
        />
      </div>

      <main className="app-main">
        <header className="app-header">
          <h1>TradingAgents · 实时分析</h1>
          <span className="subtitle">7 分析师并行架构 · token 级流式输出</span>
        </header>

        <Controls
          analysts={analysts}
          running={state.running}
          onStart={(t, d, sel) => start(t, d, sel, llmConfig)}
          onStop={stop}
        />

        {state.error && <div className="error-banner">❌ {state.error}</div>}

        {state.cards.length > 0 && <AnalystGrid cards={state.cards} onExpand={setExpandedKey} />}
      </main>

      <RightRail cards={state.cards} />

      <CardModal
        card={state.cards.find((c) => c.key === expandedKey)}
        onClose={() => setExpandedKey(null)}
      />
    </div>
  );
}
