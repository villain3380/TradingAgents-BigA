import type { CardState } from "../api/types";

interface Props {
  cards: CardState[];
}

/**
 * Right rail: shows URLs from get_news tool calls.
 *
 * The tool result cache ensures each URL appears only once (even when five
 * analysts call get_news with the same args), so a flat list is sufficient —
 * no grouping needed.
 */
export function RightRail({ cards }: Props) {
  // Gather and de-duplicate all source URLs.
  const seen = new Set<string>();
  const urls: string[] = [];
  for (const c of cards) {
    for (const t of c.tools) {
      for (const url of t.sources ?? []) {
        if (!seen.has(url)) {
          seen.add(url);
          urls.push(url);
        }
      }
    }
  }

  return (
    <aside className="right-rail">
      <div className="rail-section">
        <div className="rail-title">get_news链接</div>
        {urls.length === 0 ? (
          <div className="sources-empty">
            {cards.length === 0 ? "分析启动后显示" : "暂无"}
          </div>
        ) : (
          <div className="sources-list">
            {urls.map((url, i) => (
              <a
                key={i}
                className="source-link"
                href={url}
                target="_blank"
                rel="noreferrer"
                title={url}
              >
                <span className="source-url">{url}</span>
              </a>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
