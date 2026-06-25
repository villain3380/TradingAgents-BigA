import { useEffect, useState } from "react";
import type { LlmConfig, ProviderInfo, ModelOption, CustomProviderInput, ProvidersResponse } from "../api/types";
import {
  listProviders,
  saveProviderSelection,
  setDefaultProvider,
  createCustomProvider,
  deleteCustomProvider,
} from "../api/client";

interface Props {
  value: LlmConfig;
  onChange: (c: LlmConfig) => void;
  disabled?: boolean;
  providers: ProviderInfo[];
  defaultProvider: string | null;
  onReload: () => void;
}

const CUSTOM_NEW = "__new_custom__";

export function ConfigPanel({ value, onChange, disabled, providers, defaultProvider, onReload }: Props) {
  const [isDefault, setIsDefault] = useState(defaultProvider != null && defaultProvider === value.llm_provider);
  const [showCustomForm, setShowCustomForm] = useState(false);
  // editing existing custom provider name, or null for "new"
  const [editingCustom, setEditingCustom] = useState<string | null>(null);

  // custom form fields
  const [cName, setCName] = useState("");
  const [cBaseUrl, setCBaseUrl] = useState("");
  const [cKeyEnv, setCKeyEnv] = useState("");
  const [cApiKey, setCApiKey] = useState("");
  const [cQuick, setCQuick] = useState("");
  const [cDeep, setCDeep] = useState("");
  const [formError, setFormError] = useState("");
  // API key field for the currently-selected provider.
  const [keyInput, setKeyInput] = useState("");
  const [editingKey, setEditingKey] = useState(false);

  // Keep the "⭐ set as default" checkbox in sync with the source of truth
  // (the defaultProvider prop, refreshed by the parent after each save).
  useEffect(() => {
    setIsDefault(defaultProvider != null && defaultProvider === value.llm_provider);
  }, [defaultProvider, value.llm_provider]);

  // Local reload helper — delegates to the parent's onReload (which re-fetches
  // providers + default and passes fresh props down).
  const reload = () => onReload();

  const current: ProviderInfo | undefined = providers.find((p) => p.key === value.llm_provider);

  function persist(c: LlmConfig) {
    saveProviderSelection(c.llm_provider, {
      quick_think_llm: c.quick_think_llm,
      deep_think_llm: c.deep_think_llm,
      backend_url: c.backend_url ?? "",
    }).catch(() => {});
  }

  function update(c: LlmConfig) {
    onChange(c);
    persist(c);
  }

  function onProvider(key: string) {
    if (key === CUSTOM_NEW) {
      setEditingCustom(null);
      setCName(""); setCBaseUrl(""); setCKeyEnv(""); setCApiKey(""); setCQuick(""); setCDeep(""); setFormError("");
      setShowCustomForm(true);
      return;
    }
    setShowCustomForm(false);
    setEditingKey(false);
    setKeyInput("");
    const p = providers.find((x) => x.key === key);
    if (!p) return;
    const saved = p.selected;
    // Custom providers have no preset list → always use the saved model (free text).
    const firstQuick = p.custom
      ? saved.quick_think_llm || ""
      : saved.quick_think_llm || p.quick.find((m) => m.value !== "custom")?.value || "custom";
    const firstDeep = p.custom
      ? saved.deep_think_llm || ""
      : saved.deep_think_llm || p.deep.find((m) => m.value !== "custom")?.value || "custom";
    update({
      ...value,
      llm_provider: key,
      quick_think_llm: firstQuick,
      deep_think_llm: firstDeep,
      backend_url: (saved.backend_url || p.base_url || "") || null,
    });
    setIsDefault(false);
  }

  async function toggleDefault() {
    const next = !isDefault;
    setIsDefault(next);
    await setDefaultProvider(next ? value.llm_provider : null).catch(() => {});
    reload();
  }

  async function saveCustom() {
    setFormError("");
    if (!cName.trim()) { setFormError("请填 provider 名称"); return; }
    if (!cBaseUrl.trim()) { setFormError("请填 API Base URL"); return; }
    if (!cApiKey.trim() && !cKeyEnv.trim()) { setFormError("请填 API Key 或 API Key 变量名"); return; }
    const input: CustomProviderInput = {
      name: cName.trim(),
      base_url: cBaseUrl.trim(),
      api_key_env: cKeyEnv.trim(),
      api_key: cApiKey.trim() || undefined,
      quick_think_llm: cQuick.trim(),
      deep_think_llm: cDeep.trim(),
    };
    try {
      await createCustomProvider(input);
      await reload();
      // switch to the just-saved provider
      onChange({
        llm_provider: input.name,
        quick_think_llm: input.quick_think_llm || "",
        deep_think_llm: input.deep_think_llm || "",
        backend_url: input.base_url || null,
      });
      setShowCustomForm(false);
      setEditingCustom(null);
    } catch (e: any) {
      setFormError(e?.message || "保存失败（可能名称与内置 provider 冲突）");
    }
  }

  async function removeCustom() {
    if (!current?.custom) return;
    if (!confirm(`删除自定义 provider「${current.key}」？`)) return;
    await deleteCustomProvider(current.key).catch(() => {});
    await reload();
    // fall back to first built-in
    const first = providers.find((p) => !p.custom);
    if (first) onProvider(first.key);
  }

  function startEditCustom() {
    if (!current?.custom) return;
    setEditingCustom(current.key);
    setCName(current.key);
    setCBaseUrl(current.base_url ?? current.selected.backend_url ?? "");
    setCKeyEnv(current.api_key_env ?? "");
    setCApiKey("");  // never prefill the key; user re-types to change it
    setCQuick(current.selected.quick_think_llm);
    setCDeep(current.selected.deep_think_llm);
    setFormError("");
    setShowCustomForm(true);
  }

  function ModelSelect({ mode, modelKey }: { mode: "quick" | "deep"; modelKey: "quick_think_llm" | "deep_think_llm" }) {
    // Custom providers: no preset list → free-text input only.
    if (current?.custom) {
      return (
        <div className="model-group">
          <input
            className="input"
            placeholder="模型 ID"
            value={value[modelKey]}
            onChange={(e) => update({ ...value, [modelKey]: e.target.value })}
            disabled={disabled}
          />
        </div>
      );
    }
    const options: ModelOption[] = current?.[mode] ?? [];
    const stored = value[modelKey];
    const isCustom = stored === "custom" || !options.some((m) => m.value === stored);
    return (
      <div className="model-group">
        <select
          className="input"
          value={isCustom ? "custom" : stored}
          onChange={(e) => update({ ...value, [modelKey]: e.target.value })}
          disabled={disabled || !current}
        >
          {options.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
        {isCustom && (
          <input
            className="input"
            placeholder="自定义模型 ID"
            value={stored === "custom" ? "" : stored}
            onChange={(e) => update({ ...value, [modelKey]: e.target.value })}
            disabled={disabled}
          />
        )}
      </div>
    );
  }

  return (
    <div className="config-panel">
      <div className="config-row">
        <label className="config-label">LLM 供应商</label>
        <select className="input" value={value.llm_provider} onChange={(e) => onProvider(e.target.value)} disabled={disabled}>
          {providers.map((p) => (
            <option key={p.key} value={p.key}>
              {p.custom ? `🧩 ${p.label}` : p.label}
            </option>
          ))}
          <option value={CUSTOM_NEW}>＋ 新增自定义…</option>
        </select>
        <label className={`default-toggle ${isDefault ? "on" : ""}`} title="设为默认：headless 调用时用此配置">
          <input type="checkbox" checked={isDefault} onChange={toggleDefault} disabled={disabled} />
          <span>⭐ 设为默认</span>
        </label>
        {current?.custom && !showCustomForm && (
          <>
            <button className="btn-tiny" onClick={startEditCustom} disabled={disabled}>编辑</button>
            <button className="btn-tiny danger" onClick={removeCustom} disabled={disabled}>删除</button>
          </>
        )}
      </div>

      {showCustomForm ? (
        <div className="custom-form">
          <div className="custom-form-title">{editingCustom ? `编辑「${editingCustom}」` : "新增自定义 provider（须为 OpenAI 兼容接口）"}</div>
          <div className="config-row">
            <label className="config-label">Provider 名称</label>
            <input className="input" value={cName} onChange={(e) => setCName(e.target.value)} placeholder="如 ali_token_plan" disabled={disabled} />
          </div>
          <div className="config-row">
            <label className="config-label">API Base URL</label>
            <input className="input" value={cBaseUrl} onChange={(e) => setCBaseUrl(e.target.value)} placeholder="如 https://ark.cn-beijing.volces.com/api/v3" disabled={disabled} />
          </div>
          <div className="config-row">
            <label className="config-label">API Key 变量名</label>
            <input className="input" value={cKeyEnv} onChange={(e) => setCKeyEnv(e.target.value)} placeholder="如 ALI_TOKEN_KEY（可选，.env 回退用）" disabled={disabled} />
            <span className="hint">可选：.env 回退变量名</span>
          </div>
          <div className="config-row">
            <label className="config-label">API Key</label>
            <input className="input" type="password" value={cApiKey} onChange={(e) => setCApiKey(e.target.value)} placeholder="填入 API Key（存本地 settings.json）" disabled={disabled} />
            <span className="hint">推荐直接填，无需改 .env</span>
          </div>
          <div className="config-row">
            <label className="config-label">快速模型</label>
            <input className="input" value={cQuick} onChange={(e) => setCQuick(e.target.value)} placeholder="模型 ID" disabled={disabled} />
          </div>
          <div className="config-row">
            <label className="config-label">深度模型</label>
            <input className="input" value={cDeep} onChange={(e) => setCDeep(e.target.value)} placeholder="模型 ID" disabled={disabled} />
          </div>
          {formError && <div className="form-error">{formError}</div>}
          <div className="custom-form-actions">
            <button className="btn-primary" onClick={saveCustom} disabled={disabled}>保存</button>
            <button className="btn-tiny" onClick={() => { setShowCustomForm(false); setEditingCustom(null); }} disabled={disabled}>取消</button>
          </div>
        </div>
      ) : (
        <>
          <div className="config-row">
            <label className="config-label">快速思考模型</label>
            <ModelSelect mode="quick" modelKey="quick_think_llm" />
          </div>
          <div className="config-row">
            <label className="config-label">深度思考模型</label>
            <ModelSelect mode="deep" modelKey="deep_think_llm" />
          </div>
          <div className="config-row">
            <label className="config-label">API Base URL（可选）</label>
            <input
              className="input"
              placeholder="如 https://your-proxy.com/v1"
              value={value.backend_url ?? ""}
              onChange={(e) => update({ ...value, backend_url: e.target.value.trim() || null })}
              disabled={disabled}
            />
          </div>
          <div className="config-row">
            <label className="config-label">API Key</label>
            {editingKey ? (
              <>
                <input
                  className="input"
                  type="password"
                  placeholder="填入 API Key（存到本地 settings.json）"
                  value={keyInput}
                  onChange={(e) => setKeyInput(e.target.value)}
                  disabled={disabled}
                />
                <button
                  className="btn-tiny"
                  onClick={async () => {
                    await saveProviderSelection(value.llm_provider, {
                      quick_think_llm: value.quick_think_llm,
                      deep_think_llm: value.deep_think_llm,
                      backend_url: value.backend_url ?? "",
                      api_key: keyInput,
                    });
                    setEditingKey(false);
                    setKeyInput("");
                    reload();
                  }}
                  disabled={disabled}
                >
                  保存
                </button>
                <button className="btn-tiny" onClick={() => { setEditingKey(false); setKeyInput(""); }} disabled={disabled}>
                  取消
                </button>
              </>
            ) : (
              <>
                <span className="key-status">
                  {current?.has_key ? "✓ 已设置" : "未设置"}
                </span>
                <button className="btn-tiny" onClick={() => { setEditingKey(true); setKeyInput(""); }} disabled={disabled}>
                  {current?.has_key ? "修改" : "设置"}
                </button>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
