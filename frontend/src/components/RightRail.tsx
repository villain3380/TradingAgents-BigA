import type { CardState } from "../api/types";

interface Props {
  cards: CardState[];
}

/**
 * Right rail: shows the source URLs retrieved by each analyst's tools.
 *
 * Provenance builds trust — users see where the news/data came from. Only
 * tools that return URLs (currently get_news, which emits "Link: <url>") show
 * sources here; other tools have empty source lists and are hidden.
 */
export function RightRail({ cards }: Props) {
  // Flatten: list of {agent_label, tool, url} across all cards' tools.
  const entries: { agent: string; tool: string; url: string }[] = [];
  for (const c of cards) {
    for (const t of c.tools) {
      for (const url of t.sources ?? []) {
        entries.push({ agent: c.label, tool: t.tool, url });
      }
    }
  }

  return (
    <aside className="right-rail">
      <div className="rail-section">
        <div className="rail-title">检索来源</div>
        {entries.length === 0 ? (
          <div className="sources-empty">
            {cards.length === 0
              ? "分析启动后显示来源"
              : "暂无来源（部分数据源不返回 url）"}
          </div>
        ) : (
          <div className="sources-list">
            {entries.map((e, i) => (
              <a
                key={i}
                className="source-link"
                href={e.url}
                target="_blank"
                rel="noreferrer"
                title={`${e.agent} · ${e.tool}`}
              >
                <span className="source-agent">{e.agent}</span>
                <span className="source-url">{e.url}</span>
              </a>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
