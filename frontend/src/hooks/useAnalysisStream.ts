import { useCallback, useReducer, useRef, useState } from "react";
import type { AnalystMeta, RunState, LlmConfig } from "../api/types";
import { startAnalysis } from "../api/client";
import { makeInitial, reducer } from "../state/reducer";

/**
 * Drives one analysis run: POST /api/analyze to get a run_id, then open an
 * EventSource on /api/stream/{run_id} and feed SSE events into the reducer.
 *
 * Token events are high-frequency; React 18 batches the dispatches. If the UI
 * lags on very long reports, wrap `cards` in useDeferredValue at the call site.
 */
export function useAnalysisStream() {
  const [analysts, setAnalysts] = useState<AnalystMeta[]>([]);
  const [state, dispatch] = useReducer(reducer, null as unknown as RunState, () => makeInitial([]));
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const runIdRef = useRef<string | null>(null);
  // Re-entrancy guard: while a start is in flight (POST /api/analyze), ignore
  // further clicks so the user can't double-click into two parallel runs.
  const startingRef = useRef(false);

  const start = useCallback(
    async (ticker: string, tradeDate: string, selected: string[], config: LlmConfig) => {
      if (startingRef.current) return;  // already starting — ignore the extra click
      startingRef.current = true;

      // Immediate feedback: flip to "running" the instant the click lands, so
      // the button disables and the user sees something happened — don't wait
      // for the POST round-trip (which takes ~1-2s and otherwise looks like a
      // no-op, tempting the user to hammer the button).
      dispatch({ type: "start_pending" });

      try {
        const resp = await startAnalysis(ticker, tradeDate, selected, config);
        runIdRef.current = resp.run_id;
        setRunId(resp.run_id);
        setAnalysts(resp.analysts);
        dispatch({ type: "reset", analysts: resp.analysts });

        const es = new EventSource(`/api/stream/${resp.run_id}`);
        esRef.current = es;

        es.addEventListener("token", (e) => {
          const d = JSON.parse((e as MessageEvent).data);
          dispatch({ type: "token", agent_id: d.agent_id, text: d.text });
        });
        es.addEventListener("tool", (e) => {
          const d = JSON.parse((e as MessageEvent).data);
          dispatch({ type: "tool", agent_id: d.agent_id, tool: d.tool, toolType: d.type, sources: d.sources });
        });
        es.addEventListener("stage_done", (e) => {
          const d = JSON.parse((e as MessageEvent).data);
          dispatch({ type: "stage_done", agent_id: d.agent_id, stage: d.stage, name: d.name, report: d.report });
        });
        es.addEventListener("stats", (e) => {
          const d = JSON.parse((e as MessageEvent).data);
          dispatch({ type: "stats", ...d });
        });
        es.addEventListener("done", (e) => {
          const d = JSON.parse((e as MessageEvent).data);
          dispatch({ type: "done", signal: d.signal, report_path: d.report_path });
          es.close();
        });
        es.addEventListener("error", (e) => {
          // EventSource fires 'error' both on real (server-pushed) errors and
          // on transient connection drops. A server error carries a `data`
          // payload and is terminal — close so EventSource does NOT auto-reconnect
          // (reconnecting after the run ended yields "unknown run_id" which would
          // clobber the real error message). A transport drop has no data; let
          // EventSource retry.
          const me = e as MessageEvent;
          if (me.data) {
            try {
              const d = JSON.parse(me.data);
              dispatch({ type: "error", message: d.message });
            } catch {
              /* ignore parse errors */
            }
            es.close();  // terminal — stop the auto-reconnect
          }
        });
      } catch (e) {
        // POST /api/analyze failed — clear the pending state and surface the error.
        dispatch({ type: "error", message: String(e instanceof Error ? e.message : e) });
      } finally {
        startingRef.current = false;
      }
    },
    []
  );

  const stop = useCallback(async () => {
    // Tell the backend to cancel the graph task, then close the SSE stream.
    const rid = runIdRef.current;
    if (rid) {
      try {
        await fetch(`/api/stop/${rid}`, { method: "POST" });
      } catch {
        /* ignore — the SSE close still tears down locally */
      }
    }
    esRef.current?.close();
    esRef.current = null;
    dispatch({ type: "done", signal: "已停止" });
  }, []);

  return { state, analysts, expandedKey, setExpandedKey, start, stop, runId };
}
