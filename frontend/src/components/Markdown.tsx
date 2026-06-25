import ReactMarkdown from "react-markdown";

/**
 * Renders analyst report text as Markdown.
 *
 * Reports are streamed token-by-token, so partial markdown (e.g. an unclosed
 * table row mid-stream) is normal — react-markdown handles incomplete input
 * gracefully, re-rendering as more tokens arrive.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="md-body">
      <ReactMarkdown>{children || ""}</ReactMarkdown>
    </div>
  );
}
