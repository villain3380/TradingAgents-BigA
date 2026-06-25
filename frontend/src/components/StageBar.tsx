import type { PostStage } from "../api/types";

interface Props {
  stages: PostStage[];
  signal: string | null;
}

export function StageBar({ stages, signal }: Props) {
  return (
    <div className="stage-bar">
      {stages.map((s) => (
        <div key={s.id} className={`stage-chip ${s.done ? "done" : ""}`}>
          <span>{s.icon}</span>
          <span>{s.name}</span>
          <span>{s.done ? "✓" : "○"}</span>
        </div>
      ))}
      {signal && <div className="signal">最终信号：{signal}</div>}
    </div>
  );
}
