import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders analyst report text as Markdown (with GFM — tables, strikethrough,
 * task lists, autolinks). react-markdown v10 does NOT enable GFM by default,
 * so without this plugin the reports' Markdown tables render as plain text.
 *
 * Reports are streamed token-by-token, so partial markdown (e.g. an unclosed
 * table row mid-stream) is normal — react-markdown handles incomplete input
 * gracefully, re-rendering as more tokens arrive.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="md-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children || ""}</ReactMarkdown>
    </div>
  );
}
