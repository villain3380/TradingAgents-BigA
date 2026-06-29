import { useEffect, useState, useCallback } from "react";

interface PromptMeta {
  name: string;
  label: string;
  icon: string;
  variables: boolean;
  description: string;
}

export function PromptEditor() {
  const [prompts, setPrompts] = useState<PromptMeta[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [defaultContent, setDefaultContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetch("/api/prompts")
      .then((r) => r.json())
      .then(setPrompts)
      .catch(() => {});
  }, []);

  const handleClick = useCallback(async (name: string) => {
    if (selected === name) {
      // Toggle off — collapse editor
      setSelected(null);
      setMessage("");
      return;
    }
    setSelected(name);
    setMessage("");
    try {
      const r = await fetch(`/api/prompts/${name}`);
      const d = await r.json();
      setContent(d.content);
      setDefaultContent(d.default);
    } catch {
      setContent("");
    }
  }, [selected]);

  const save = useCallback(async () => {
    setSaving(true);
    setMessage("");
    try {
      await fetch(`/api/prompts/${selected}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      setMessage("✓ 已保存");
    } catch {
      setMessage("✗ 保存失败");
    } finally {
      setSaving(false);
    }
  }, [selected, content]);

  const reset = useCallback(async () => {
    if (!confirm("恢复为默认 prompt？当前修改将丢失。")) return;
    setSaving(true);
    try {
      await fetch(`/api/prompts/${selected}/reset`, { method: "POST" });
      setContent(defaultContent);
      setMessage("✓ 已恢复默认");
    } catch {
      setMessage("✗ 恢复失败");
    } finally {
      setSaving(false);
    }
  }, [selected, defaultContent]);

  const exit = useCallback(async () => {
    if (selected) {
      // Discard local edits — reload from file
      try {
        const r = await fetch(`/api/prompts/${selected}`);
        const d = await r.json();
        setContent(d.content);
      } catch {}
    }
    setSelected(null);
    setMessage("");
  }, [selected]);

  const sel = prompts.find((p) => p.name === selected);

  return (
    <div className="prompt-editor rail-section">
      <div className="rail-title">📝 Prompt 编辑器</div>

      <div className="prompt-list">
        {prompts.map((p) => (
          <button
            key={p.name}
            className={`prompt-item${p.name === selected ? " selected" : ""}`}
            onClick={() => handleClick(p.name)}
          >
            <span className="prompt-icon">{p.icon}</span>
            <span className="prompt-label">{p.label}</span>
            {p.variables && <span className="prompt-var-badge">模板</span>}
          </button>
        ))}
      </div>

      {sel && (
        <div className="prompt-detail">
          <div className="prompt-detail-header">
            <span>{sel.icon} {sel.label}</span>
            <span className="prompt-desc">{sel.description}</span>
            {sel.variables && (
              <span className="prompt-var-hint">含模板变量，修改时请保留 {"{变量名}"} 占位符</span>
            )}
          </div>

          <textarea
            className="prompt-textarea"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={20}
          />

          <div className="prompt-actions">
            <button className="btn-prompt-save" onClick={save} disabled={saving}>
              💾 保存
            </button>
            <button className="btn-prompt-exit" onClick={exit}>
              ✕ 退出编辑
            </button>
            <button className="btn-prompt-reset" onClick={reset} disabled={saving}>
              ↩ 默认
            </button>
            {message && <span className="prompt-msg">{message}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
