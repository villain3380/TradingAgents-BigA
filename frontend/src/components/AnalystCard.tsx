import type { CardState } from "../api/types";

interface Props {
  card: CardState;
  onClick: () => void;
}

function statusDot(status: CardState["status"]): string {
  if (status === "done") return "🟢";
  if (status === "streaming") return "🟠";
  return "⚪";
}

export function AnalystCard({ card, onClick }: Props) {
  return (
    <div className={`card ${card.status}`} onClick={onClick}>
      <header className="card-header">
        <span className="card-icon">{card.icon}</span>
        <span className="card-label">{card.label}</span>
        <span className="card-dot">{statusDot(card.status)}</span>
      </header>
      <div className="card-body">
        {card.text || (card.status === "pending" ? "等待中…" : "")}
        {card.status === "streaming" && <span className="cursor">▍</span>}
      </div>
      {card.tools.length > 0 && (
        <div className="card-tools">
          {card.tools.slice(-3).map((t, i) => (
            <span key={i} className="tool-chip">
              ⚡{t.tool}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
