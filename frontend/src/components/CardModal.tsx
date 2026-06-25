import { useEffect, useRef, useState } from "react";
import type { CardState } from "../api/types";

interface Props {
  card: CardState | undefined;
  onClose: () => void;
}

export function CardModal({ card, onClose }: Props) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const toolsRef = useRef<HTMLDivElement>(null);
  // Text pane : tool pane ratio (percent for text pane). Default 70 (7:3).
  const [ratio, setRatio] = useState(70);
  const dragging = useRef(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Auto-scroll text pane as tokens stream in.
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [card?.text]);

  // Drag-to-resize the text/tools split.
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const overlay = document.querySelector(".modal") as HTMLElement | null;
      if (!overlay) return;
      const rect = overlay.getBoundingClientRect();
      const pct = ((e.clientY - rect.top) / rect.height) * 100;
      setRatio(Math.max(25, Math.min(85, pct)));
    };
    const onUp = () => {
      dragging.current = false;
      document.body.style.cursor = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  if (!card) return null;
  const hasTools = card.tools.length > 0;
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header className="modal-header">
          <span>
            {card.icon} {card.label} {card.status === "streaming" && "🟠"}
            {card.status === "done" && "🟢"}
          </span>
          <button className="modal-close" onClick={onClose}>
            ✕
          </button>
        </header>

        {hasTools ? (
          <div className="modal-split">
            <div className="modal-text-pane" style={{ height: `${ratio}%` }}>
              <div className="pane-title">输出</div>
              <div className="modal-body" ref={bodyRef}>
                <pre className="modal-text">{card.text}</pre>
                {card.status === "streaming" && <span className="cursor">▍</span>}
              </div>
            </div>
            <div className="modal-divider" onMouseDown={() => { dragging.current = true; document.body.style.cursor = "row-resize"; }}>
              <span className="divider-grip">⋯</span>
            </div>
            <div className="modal-tools-pane" style={{ height: `${100 - ratio}%` }}>
              <div className="pane-title">工具调用（{card.tools.length}）</div>
              <div className="modal-tools-scroll" ref={toolsRef}>
                {card.tools.map((t, i) => (
                  <div key={i} className="modal-tool-row">
                    <span>{t.type === "tool_start" ? "▶" : "✓"}</span>
                    <span>{t.tool}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="modal-body full" ref={bodyRef}>
            <pre className="modal-text">{card.text}</pre>
            {card.status === "streaming" && <span className="cursor">▍</span>}
          </div>
        )}
      </div>
    </div>
  );
}
