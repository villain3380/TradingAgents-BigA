import { useEffect, useRef, useState } from "react";
import type { AnalystMeta } from "../api/types";

interface Props {
  analysts: AnalystMeta[];
  running: boolean;
  onStart: (ticker: string, date: string, selected: string[]) => void;
  onStop: () => void;
}

export function Controls({ analysts, running, onStart, onStop }: Props) {
  const [ticker, setTicker] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [selected, setSelected] = useState<string[]>([]);
  const touched = useRef(false);

  // Default to "all selected" once the analyst list loads, until the user
  // manually toggles. Fixes the bug where selected stayed [] because
  // useState(analysts.map(...)) ran before the fetch resolved.
  useEffect(() => {
    if (!touched.current && analysts.length && selected.length === 0) {
      setSelected(analysts.map((a) => a.key));
    }
  }, [analysts, selected.length]);

  const toggle = (key: string) => {
    touched.current = true;
    setSelected((s) => (s.includes(key) ? s.filter((k) => k !== key) : [...s, key]));
  };

  return (
    <div className="controls">
      <div className="controls-row">
        <input
          className="input"
          placeholder="股票代码 如 000001"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          disabled={running}
        />
        <input
          className="input date"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          disabled={running}
        />
        {running ? (
          <button className="btn-stop" onClick={onStop}>
            ⏹ 停止
          </button>
        ) : (
          <button
            className="btn-primary"
            disabled={!ticker || selected.length === 0}
            onClick={() => onStart(ticker, date, selected)}
          >
            开始分析
          </button>
        )}
      </div>

      <div className="toggles-title">分析师（勾选启用，并行执行）</div>
      <div className="analyst-toggles">
        {analysts.length === 0 && <span className="muted-hint">正在加载分析师列表…（确认 API server 已启动）</span>}
        {analysts.map((a) => (
          <label key={a.key} className={`toggle ${selected.includes(a.key) ? "on" : ""}`}>
            <input
              type="checkbox"
              checked={selected.includes(a.key)}
              onChange={() => toggle(a.key)}
              disabled={running}
            />
            <span>
              {a.icon} {a.label}
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}
