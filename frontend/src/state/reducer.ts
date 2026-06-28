import type { AnalystMeta, RunState } from "../api/types";
import { POST_STAGE_DEFS as POSTS, STREAMING_STAGE_AGENTS } from "../api/types";

export type Action =
  | { type: "reset"; analysts: AnalystMeta[] }
  | { type: "start_pending" }
  | { type: "token"; agent_id: string; text: string }
  | { type: "tool"; agent_id: string; tool: string; toolType: string; sources?: string[] }
  | { type: "stage_done"; agent_id?: string; stage?: string; name?: string; report?: string }
  | { type: "stats"; llm_calls: number; tool_calls: number; tokens_in: number; tokens_out: number; elapsed: number }
  | { type: "done"; signal: string; elapsed?: number; report_path?: string }
  | { type: "error"; message: string };

/** Mark the first non-done postStage as active — but ONLY while a run is in
 * progress. Before the user clicks start (running=false) nothing flashes.
 * Fixes the "all cards green, nothing changing" gap: after risk debators
 * finish, the risk stage stays active (pulse) until PM's judge_decision lands. */
function withActiveProgress(postStages: RunState["postStages"], running: boolean): RunState["postStages"] {
  if (!running) return postStages.map((p) => ({ ...p, active: false }));
  let foundPending = false;
  return postStages.map((p) => {
    if (p.done) return { ...p, active: false };
    if (!foundPending) {
      foundPending = true;
      return { ...p, active: true };
    }
    return { ...p, active: false };
  });
}

export function makeInitial(analysts: AnalystMeta[], running = false): RunState {
  // Analyst cards come from the registry; downstream streaming agents (bull/
  // bear/quality_gate/risk debators) are added too so their live output shows.
  const cards = [
    ...analysts.map((a) => ({
      key: a.key, label: a.label, icon: a.icon,
      status: "pending" as const, text: "", tools: [],
    })),
    ...STREAMING_STAGE_AGENTS.map((a) => ({
      key: a.key, label: a.label, icon: a.icon,
      status: "pending" as const, text: "", tools: [],
    })),
  ];
  const postStages = POSTS.map((p) => ({ ...p, done: false, active: false }));
  return {
    cards,
    // No active stage before the user starts a run — nothing flashes.
    postStages: withActiveProgress(postStages, false),
    signal: null,
    reportPath: null,
    error: null,
    running,
    stats: { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0, elapsed: 0 },
    runId: null,
  };
}

export function reducer(state: RunState, action: Action): RunState {
  switch (action.type) {
    case "reset":
      // reset fires once /api/analyze returns — now running=true, light the first stage.
      return makeInitial(action.analysts, true);

    case "start_pending":
      // Click landed — running=true, but stages don't flash yet (reset hasn't
      // fired; cards/postStages get rebuilt on reset). Don't touch postStages here.
      return { ...state, running: true, signal: null, error: null };

    case "token": {
      return {
        ...state,
        cards: state.cards.map((c) =>
          c.key === action.agent_id
            ? { ...c, status: "streaming", text: c.text + action.text }
            : c
        ),
      };
    }

    case "tool": {
      return {
        ...state,
        cards: state.cards.map((c) =>
          c.key === action.agent_id
            ? { ...c, status: "streaming", tools: [...c.tools, { tool: action.tool, type: action.toolType, ts: Date.now(), sources: action.sources }] }
            : c
        ),
      };
    }

    case "stage_done": {
      if (action.agent_id) {
        return {
          ...state,
          cards: state.cards.map((c) =>
            c.key === action.agent_id
              ? { ...c, status: "done", report: action.report ?? c.report ?? c.text }
              : c
          ),
        };
      }
      // Downstream stage done → re-derive active (next pending becomes active,
      // only while still running).
      const postStages = state.postStages.map((p) =>
        p.id === action.stage ? { ...p, done: true, active: false } : p
      );
      return { ...state, postStages: withActiveProgress(postStages, state.running) };
    }

    case "stats":
      return { ...state, stats: { llm_calls: action.llm_calls, tool_calls: action.tool_calls, tokens_in: action.tokens_in, tokens_out: action.tokens_out, elapsed: action.elapsed } };

    case "done":
      // All stages done — clear active flags.
      return { ...state, signal: action.signal, reportPath: action.report_path ?? null, running: false,
        postStages: state.postStages.map((p) => ({ ...p, active: false, done: true })) };

    case "error":
      return { ...state, error: action.message, running: false,
        postStages: withActiveProgress(state.postStages, false) };

    default:
      return state;
  }
}

export const _POSTS = POSTS;
