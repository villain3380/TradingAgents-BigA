import type { AnalystMeta, RunState } from "../api/types";
import { POST_STAGE_DEFS as POSTS, STREAMING_STAGE_AGENTS } from "../api/types";

export type Action =
  | { type: "reset"; analysts: AnalystMeta[] }
  | { type: "start_pending" }
  | { type: "token"; agent_id: string; text: string }
  | { type: "tool"; agent_id: string; tool: string; toolType: string }
  | { type: "stage_done"; agent_id?: string; stage?: string; name?: string; report?: string }
  | { type: "stats"; llm_calls: number; tool_calls: number; tokens_in: number; tokens_out: number; elapsed: number }
  | { type: "done"; signal: string; elapsed?: number }
  | { type: "error"; message: string };

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
  return {
    cards,
    postStages: POSTS.map((p) => ({ ...p, done: false })),
    signal: null,
    error: null,
    running,
    stats: { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0, elapsed: 0 },
    runId: null,
  };
}

export function reducer(state: RunState, action: Action): RunState {
  switch (action.type) {
    case "reset":
      return makeInitial(action.analysts, true);

    case "start_pending":
      // Click landed — flip to running immediately (disables the button) while
      // the POST /api/analyze is in flight. Cards are replaced once it returns.
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
            ? { ...c, status: "streaming", tools: [...c.tools, { tool: action.tool, type: action.toolType, ts: Date.now() }] }
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
      return {
        ...state,
        postStages: state.postStages.map((p) =>
          p.id === action.stage ? { ...p, done: true } : p
        ),
      };
    }

    case "stats":
      return { ...state, stats: { llm_calls: action.llm_calls, tool_calls: action.tool_calls, tokens_in: action.tokens_in, tokens_out: action.tokens_out, elapsed: action.elapsed } };

    case "done":
      return { ...state, signal: action.signal, running: false };

    case "error":
      return { ...state, error: action.message, running: false };

    default:
      return state;
  }
}

export const _POSTS = POSTS;
