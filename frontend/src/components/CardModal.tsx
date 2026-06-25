import { useEffect, useRef, useState } from "react";
import type { CardState } from "../api/types";
import { Markdown } from "./Markdown";

interface Props {
  card: CardState | undefined;
  onClose: () => void;
}

export function CardModal({ card, onClose }: Props) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const toolsRef = useRef<HTMLDivElement>(null);
  // Text pane : tool pane ratio (percent for text pane). Default 88 — text is
  // the point; tools are a secondary aid getting a small fixed slice. Drag to
  // adjust between 60% and 97%.
  const [ratio, setRatio] = useState(88);
  const dragging = useRef(false);
  // Does the user want live-follow (auto-scroll to bottom on new tokens)?
  // True only while they're parked at the bottom. Scrolling up flips it false
  // so they can read freely; scrolling back to the bottom re-enables it. This
  // decouples "where new text appears" from "what the user is looking at".
  const stickToBottom = useRef(true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Auto-follow ONLY when the user is already at the bottom. New tokens arriving
  // while they've scrolled up to read earlier text must NOT yank them back down.
  useEffect(() => {
    if (stickToBottom.current && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [card?.text]);

  // Track the user's scroll position to decide whether to follow.
  function onBodyScroll() {
    const el = bodyRef.current;
    if (!el) return;
    // Consider "at bottom" if within 24px of the end (covers sub-pixel rounding).
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    stickToBottom.current = atBottom;
  }

  // Drag-to-resize the text/tools split. Use the split container's bounding
  // rect (not the whole modal) so the ratio maps to the visible panes.
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const split = document.querySelector(".modal-split") as HTMLElement | null;
      if (!split) return;
      const rect = split.getBoundingClientRect();
      const pct = ((e.clientY - rect.top) / rect.height) * 100;
      setRatio(Math.max(60, Math.min(97, pct)));
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
            <div className="modal-text-pane" style={{ flex: `${ratio} 1 0` }}>
              <div className="pane-title">报告</div>
              <div className="modal-body" ref={bodyRef} onScroll={onBodyScroll}>
                <Markdown>{card.text}</Markdown>
                {card.status === "streaming" && <span className="cursor">▍</span>}
              </div>
            </div>
            <div className="modal-divider" onMouseDown={() => { dragging.current = true; document.body.style.cursor = "row-resize"; }}>
              <span className="divider-grip">⋯</span>
            </div>
            <div className="modal-tools-pane" style={{ flex: `${100 - ratio} 1 0` }}>
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
          <div className="modal-body full" ref={bodyRef} onScroll={onBodyScroll}>
            <Markdown>{card.text}</Markdown>
            {card.status === "streaming" && <span className="cursor">▍</span>}
          </div>
        )}
      </div>
    </div>
  );
}
