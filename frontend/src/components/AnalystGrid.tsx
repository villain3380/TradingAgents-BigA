import type { CardState } from "../api/types";
import { AnalystCard } from "./AnalystCard";

interface Props {
  cards: CardState[];
  onExpand: (key: string) => void;
}

export function AnalystGrid({ cards, onExpand }: Props) {
  return (
    <div className="grid">
      {cards.map((c) => (
        <AnalystCard key={c.key} card={c} onClick={() => onExpand(c.key)} />
      ))}
    </div>
  );
}
