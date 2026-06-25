export interface AnalystMeta {
  key: string;
  label: string;
  icon: string;
  report_field: string;
}

export type CardStatus = "pending" | "streaming" | "done";

export interface CardState {
  key: string;
  label: string;
  icon: string;
  status: CardStatus;
  text: string; // accumulated token text (live display)
  report?: string; // final report (from stage_done) once done
  tools: { tool: string; type: string; ts: number; sources?: string[] }[];
}

export interface PostStage {
  id: string;
  name: string;
  icon: string;
  done: boolean;
  active: boolean; // currently running — shows "进行中" pulse, fixes the "all green, looks stuck" gap
}

export interface AnalyzeResponse {
  run_id: string;
  ticker: string;
  trade_date: string;
  analysts: AnalystMeta[];
}

export interface RunState {
  cards: CardState[];
  postStages: PostStage[];
  signal: string | null;
  error: string | null;
  running: boolean;
  stats: { llm_calls: number; tool_calls: number; tokens_in: number; tokens_out: number; elapsed: number };
  runId: string | null;
}

export interface ModelOption {
  label: string;
  value: string;
}

export interface ProviderInfo {
  key: string;
  label: string;
  custom: boolean;
  base_url?: string;       // custom providers only
  api_key_env?: string;    // custom providers only (legacy .env fallback)
  has_key?: boolean;       // true if an api_key is stored for this provider
  quick: ModelOption[];
  deep: ModelOption[];
  selected: { quick_think_llm: string; deep_think_llm: string; backend_url: string };
}

export interface CustomProviderInput {
  name: string;
  base_url: string;
  api_key_env?: string;
  api_key?: string;
  quick_think_llm?: string;
  deep_think_llm?: string;
}

export interface ProvidersResponse {
  providers: ProviderInfo[];
  default_provider: string | null;
}

export interface LlmConfig {
  llm_provider: string;
  quick_think_llm: string;
  deep_think_llm: string;
  backend_url?: string | null;
}

export const POST_STAGE_DEFS: { id: string; name: string; icon: string }[] = [
  { id: "quality_gate", name: "质量门控", icon: "✅" },
  { id: "debate", name: "多空辩论", icon: "⚔️" },
  { id: "trader", name: "交易决策", icon: "💹" },
  { id: "risk", name: "风控评估", icon: "🛡️" },
  { id: "pm", name: "最终决策", icon: "👔" },
];

// Downstream agents that stream tokens (free-text nodes). The frontend renders
// each as its own card so the debate / risk stages show live output instead of
// a dead "running" badge. Keys match the agent_id passed to stream_invoke.
export const STREAMING_STAGE_AGENTS: { key: string; label: string; icon: string }[] = [
  { key: "quality_gate", label: "质量门控", icon: "✅" },
  { key: "bull", label: "多方辩论", icon: "🐂" },
  { key: "bear", label: "空方辩论", icon: "🐻" },
  { key: "aggressive", label: "激进风控", icon: "🔥" },
  { key: "conservative", label: "保守风控", icon: "🛡️" },
  { key: "neutral", label: "中立风控", icon: "⚖️" },
];
