import type { AnalystMeta, AnalyzeResponse, ProviderInfo, ProvidersResponse, LlmConfig, CustomProviderInput } from "./types";

export async function listAnalysts(): Promise<AnalystMeta[]> {
  const r = await fetch("/api/analysts");
  return r.json();
}

export async function listProviders(): Promise<ProvidersResponse> {
  const r = await fetch("/api/providers");
  return r.json();
}

export async function saveProviderSelection(
  provider: string,
  sel: { quick_think_llm: string; deep_think_llm: string; backend_url: string; api_key?: string | null }
): Promise<void> {
  await fetch(`/api/providers/${provider}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sel),
  });
}

export async function setDefaultProvider(provider: string | null): Promise<void> {
  await fetch("/api/settings/default-provider", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider }),
  });
}

export async function createCustomProvider(input: CustomProviderInput): Promise<void> {
  await fetch("/api/providers/custom", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function deleteCustomProvider(name: string): Promise<void> {
  await fetch(`/api/providers/custom/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export async function startAnalysis(
  ticker: string,
  tradeDate: string,
  analysts: string[],
  config: LlmConfig
): Promise<AnalyzeResponse> {
  const r = await fetch("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, trade_date: tradeDate, analysts, config }),
  });
  return r.json();
}
