"""User settings persistence for the single-user TradingAgents install.

Stores per-provider LLM selections (which quick/deep model, optional base_url
override) and the default provider, in a JSON file under the user's
``~/.tradingagents-biga/`` dir. Single-user by design: one file, one writer, no
locking — see the project's "single-user, no auth" stance.

API keys are deliberately NOT stored here — they stay in ``.env`` (one env var
per provider, see llm_clients/openai_client.py). This file only holds
non-sensitive preferences, so it could be shared/committed if a user wanted
(though ~/.tradingagents-biga is user-local, not the repo).

Step 1 scope: persistence of model/base_url selections + default provider.
The provider->api-key mapping is still hardcoded in openai_client.py; custom
new providers (Step 2) are not yet supported.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


def settings_path() -> Path:
    """Return the settings.json path under the TradingAgents home dir."""
    home = os.path.join(os.path.expanduser("~"), ".tradingagents-biga")
    return Path(home) / "settings.json"


def _ensure_dir() -> None:
    settings_path().parent.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    """Load settings, returning an empty skeleton if missing/corrupt.

    Skeleton: ``{"default_provider": None, "providers": {}}``.
    """
    p = settings_path()
    if not p.exists():
        return {"default_provider": None, "providers": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"default_provider": None, "providers": {}}
    # Normalise: guarantee both keys exist with correct types.
    data.setdefault("default_provider", None)
    data.setdefault("providers", {})
    if not isinstance(data.get("providers"), dict):
        data["providers"] = {}
    return data


def save_settings(data: dict[str, Any]) -> None:
    """Atomically write settings (temp file + replace) so a crash can't corrupt."""
    _ensure_dir()
    p = settings_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def get_provider_selection(provider: str) -> dict[str, Any]:
    """Return the saved selection for one provider: quick/deep model + base_url + api_key.

    Missing keys → empty string. Missing provider → all empty.
    """
    s = load_settings()
    entry = s.get("providers", {}).get(provider, {})
    return {
        "quick_think_llm": entry.get("quick_think_llm", ""),
        "deep_think_llm": entry.get("deep_think_llm", ""),
        "backend_url": entry.get("backend_url", ""),
        "api_key": entry.get("api_key", ""),
    }


def set_provider_selection(
    provider: str,
    quick_think_llm: Optional[str] = None,
    deep_think_llm: Optional[str] = None,
    backend_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Update one provider's selection and persist. Returns the full settings.

    Only writes the fields that are not None (so a caller can update just the
    quick model without clobbering the deep model). Pass ``""`` to clear.
    ``api_key`` is stored plaintext in settings.json — this file lives in the
    user's home dir (~/.tradingagents-biga/) and is never committed to the repo, so
    it's no less safe than .env. The .env env-var fallback still works for
    users who prefer that.
    """
    s = load_settings()
    providers = s.setdefault("providers", {})
    entry = providers.setdefault(provider, {})
    if quick_think_llm is not None:
        entry["quick_think_llm"] = quick_think_llm
    if deep_think_llm is not None:
        entry["deep_think_llm"] = deep_think_llm
    if backend_url is not None:
        entry["backend_url"] = backend_url
    if api_key is not None:
        entry["api_key"] = api_key
    save_settings(s)
    return s


def get_provider_api_key(provider: str) -> str:
    """Return the saved api_key for a provider, or "" if none stored."""
    return load_settings().get("providers", {}).get(provider, {}).get("api_key", "")


def set_default_provider(provider: Optional[str]) -> dict[str, Any]:
    """Set (or clear with None) the default provider and persist."""
    s = load_settings()
    s["default_provider"] = provider
    save_settings(s)
    return s


def get_default_provider() -> Optional[str]:
    return load_settings().get("default_provider")


# --- Custom providers (Step 2) ---------------------------------------------
#
# A custom provider is a user-defined OpenAI-compatible endpoint: a name
# (e.g. "ali_token_plan"), a base_url, and the *name* of the env var that
# holds the API key (e.g. "CUSTOM_API_KEY"). The real key is never stored
# here — only the variable name; the user puts the actual key in .env.
#
# Built-in providers (glm/deepseek/...) are NOT stored as custom providers;
# their base_url/key mapping stays hardcoded in openai_client._PROVIDER_CONFIG.
# Custom providers are merged on top at runtime so create_llm_client accepts
# them transparently.

def list_custom_providers() -> dict[str, dict[str, str]]:
    """Return {provider_name: {base_url, api_key_env}} for all custom providers."""
    return dict(load_settings().get("custom_providers", {}) or {})


def get_custom_provider(name: str) -> Optional[dict[str, str]]:
    """Return one custom provider's {base_url, api_key_env} or None."""
    return list_custom_providers().get(name)


def upsert_custom_provider(
    name: str,
    base_url: str,
    api_key_env: str,
) -> dict[str, Any]:
    """Create or update a custom provider. Returns the full settings.

    ``name`` must be non-empty and not collide with a built-in provider.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("provider 名称不能为空")
    # Guard against shadowing built-ins (factory routes those to fixed clients).
    from .llm_clients.factory import builtin_provider_keys
    if name.lower() in {k.lower() for k in builtin_provider_keys()}:
        raise ValueError(f"名称 '{name}' 与内置 provider 冲突，请换一个")
    s = load_settings()
    customs = s.setdefault("custom_providers", {})
    customs[name] = {"base_url": base_url, "api_key_env": api_key_env}
    save_settings(s)
    return s


def delete_custom_provider(name: str) -> dict[str, Any]:
    """Remove a custom provider. Clear default_provider if it pointed here."""
    s = load_settings()
    customs = s.get("custom_providers", {}) or {}
    if name in customs:
        del customs[name]
    if s.get("default_provider") == name:
        s["default_provider"] = None
    save_settings(s)
    return s
