"""Remote text LLM settings (OpenAI-compatible). Separate from vision VLM."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Mapping

from src.app.config import load_config

REMOTE_LLM_MODE_LOCAL = "local"
REMOTE_LLM_MODE_CLOUD = "cloud"
REMOTE_LLM_PRESET_CUSTOM = "custom"

DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
LEGACY_DEEPSEEK_MODELS = {
    "deepseek-chat": DEFAULT_DEEPSEEK_MODEL,
    "deepseek-reasoner": DEFAULT_DEEPSEEK_MODEL,
}

DEFAULT_REMOTE_LLM_CONFIG = {
    "provider_mode": REMOTE_LLM_MODE_CLOUD,
    "provider_preset": "deepseek",
    "base_url": "https://api.deepseek.com/v1",
    "model": DEFAULT_DEEPSEEK_MODEL,
    "api_keys": {},
    "timeout_sec": 180,
    "max_tokens": 4096,
}

REMOTE_LLM_PRESETS: dict[str, dict[str, str]] = {
    "lm_studio": {
        "mode": REMOTE_LLM_MODE_LOCAL,
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "local-model",
    },
    "ollama": {
        "mode": REMOTE_LLM_MODE_LOCAL,
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5",
    },
    "deepseek": {
        "mode": REMOTE_LLM_MODE_CLOUD,
        "base_url": "https://api.deepseek.com/v1",
        "model": DEFAULT_DEEPSEEK_MODEL,
    },
    "openai": {
        "mode": REMOTE_LLM_MODE_CLOUD,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "dashscope": {
        "mode": REMOTE_LLM_MODE_CLOUD,
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "siliconflow": {
        "mode": REMOTE_LLM_MODE_CLOUD,
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
    },
    "moonshot": {
        "mode": REMOTE_LLM_MODE_CLOUD,
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-auto",
    },
}

LOCAL_LLM_PRESET_IDS = ("lm_studio", "ollama", REMOTE_LLM_PRESET_CUSTOM)
CLOUD_LLM_PRESET_IDS = ("deepseek", "openai", "dashscope", "siliconflow", "moonshot", REMOTE_LLM_PRESET_CUSTOM)
REMOTE_LLM_API_KEY_PRESET_IDS = frozenset(CLOUD_LLM_PRESET_IDS)


def normalize_remote_llm_provider_mode(value, *, default: str = REMOTE_LLM_MODE_CLOUD) -> str:
    text = str(value or "").strip().lower()
    if text in {REMOTE_LLM_MODE_LOCAL, REMOTE_LLM_MODE_CLOUD}:
        return text
    fallback = str(default or REMOTE_LLM_MODE_CLOUD).strip().lower()
    return fallback if fallback in {REMOTE_LLM_MODE_LOCAL, REMOTE_LLM_MODE_CLOUD} else REMOTE_LLM_MODE_CLOUD


def normalize_remote_llm_provider_preset(value, *, mode: str | None = None) -> str:
    text = str(value or "").strip().lower()
    if text == REMOTE_LLM_PRESET_CUSTOM:
        return REMOTE_LLM_PRESET_CUSTOM
    if text in REMOTE_LLM_PRESETS:
        preset_mode = REMOTE_LLM_PRESETS[text]["mode"]
        if mode and normalize_remote_llm_provider_mode(mode) != preset_mode:
            return REMOTE_LLM_PRESET_CUSTOM
        return text
    return REMOTE_LLM_PRESET_CUSTOM


def get_remote_llm_preset_defaults(preset_id: str) -> dict[str, str]:
    preset = REMOTE_LLM_PRESETS.get(str(preset_id or "").strip().lower())
    return dict(preset) if preset else {}


def list_remote_llm_preset_ids(*, mode: str) -> tuple[str, ...]:
    normalized_mode = normalize_remote_llm_provider_mode(mode)
    if normalized_mode == REMOTE_LLM_MODE_CLOUD:
        return CLOUD_LLM_PRESET_IDS
    return LOCAL_LLM_PRESET_IDS


def normalize_remote_llm_api_keys(raw: Mapping[str, Any] | None) -> dict[str, str]:
    payload = dict(raw or {}) if isinstance(raw, Mapping) else {}
    out: dict[str, str] = {}
    for key, value in payload.items():
        preset = normalize_remote_llm_provider_preset(str(key or ""))
        text = str(value or "").strip()
        if preset in REMOTE_LLM_API_KEY_PRESET_IDS and text:
            out[preset] = text
    return out


def remote_llm_preset_supports_api_key(preset_id: str, *, mode: str | None = None) -> bool:
    preset = normalize_remote_llm_provider_preset(preset_id, mode=mode)
    if preset == REMOTE_LLM_PRESET_CUSTOM:
        return normalize_remote_llm_provider_mode(mode) == REMOTE_LLM_MODE_CLOUD
    return preset in REMOTE_LLM_API_KEY_PRESET_IDS


def get_remote_llm_api_key_for_preset(
    raw_remote_llm: Mapping[str, Any],
    preset_id: str,
    *,
    mode: str | None = None,
) -> str:
    preset = normalize_remote_llm_provider_preset(preset_id, mode=mode)
    if not remote_llm_preset_supports_api_key(preset, mode=mode):
        return ""
    api_keys = normalize_remote_llm_api_keys(raw_remote_llm.get("api_keys"))
    return str(api_keys.get(preset, "") or "").strip()


def set_remote_llm_api_key_for_preset(
    api_keys: Mapping[str, Any] | None,
    preset_id: str,
    value: str,
    *,
    mode: str | None = None,
) -> dict[str, str]:
    merged = normalize_remote_llm_api_keys(api_keys)
    preset = normalize_remote_llm_provider_preset(preset_id, mode=mode)
    if not remote_llm_preset_supports_api_key(preset, mode=mode):
        return merged
    text = str(value or "").strip()
    if text:
        merged[preset] = text
    else:
        merged.pop(preset, None)
    return merged


def get_active_remote_llm_api_key(settings: Mapping[str, Any]) -> str:
    mode = normalize_remote_llm_provider_mode(settings.get("provider_mode", REMOTE_LLM_MODE_CLOUD))
    preset = normalize_remote_llm_provider_preset(
        settings.get("provider_preset", REMOTE_LLM_PRESET_CUSTOM),
        mode=mode,
    )
    return get_remote_llm_api_key_for_preset(settings, preset, mode=mode)


def build_remote_llm_auth_headers(settings: Mapping[str, Any]) -> dict[str, str]:
    api_key = get_active_remote_llm_api_key(settings)
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def resolve_remote_llm_provider_settings(raw_remote_llm: Mapping[str, Any]) -> tuple[str, str]:
    raw = dict(raw_remote_llm or {})
    has_explicit_mode = bool(str(raw.get("provider_mode", "") or "").strip())
    has_explicit_preset = bool(str(raw.get("provider_preset", "") or "").strip())
    explicit_mode = str(raw.get("provider_mode", "") or "").strip().lower()
    explicit_preset = str(raw.get("provider_preset", "") or "").strip().lower()
    if has_explicit_preset and explicit_preset in REMOTE_LLM_PRESETS:
        preset_mode = REMOTE_LLM_PRESETS[explicit_preset]["mode"]
        mode = (
            normalize_remote_llm_provider_mode(explicit_mode, default=preset_mode)
            if has_explicit_mode
            else preset_mode
        )
        return mode, normalize_remote_llm_provider_preset(explicit_preset, mode=mode)
    if has_explicit_mode and explicit_preset == REMOTE_LLM_PRESET_CUSTOM:
        return normalize_remote_llm_provider_mode(explicit_mode), REMOTE_LLM_PRESET_CUSTOM
    if has_explicit_mode:
        mode = normalize_remote_llm_provider_mode(explicit_mode)
        return mode, normalize_remote_llm_provider_preset(explicit_preset, mode=mode)
    return REMOTE_LLM_MODE_CLOUD, "deepseek"


def _normalize_base_url(base_url: str) -> str:
    text = str(base_url or "").strip().rstrip("/")
    if not text:
        raise ValueError("remote LLM base_url is required")
    if not text.endswith("/v1"):
        text = f"{text}/v1" if not text.endswith("/v1/") else text.rstrip("/")
    return text


def migrate_remote_llm_model(model: str) -> str:
    text = str(model or "").strip()
    return LEGACY_DEEPSEEK_MODELS.get(text, text)


def pick_available_text_llm_model(configured: str, available: list[str] | None) -> str:
    configured_id = migrate_remote_llm_model(configured)
    names = [str(item).strip() for item in (available or []) if str(item).strip()]
    if configured_id and configured_id in names:
        return configured_id
    text_models = [item for item in names if "vision" not in item.lower()]
    for preferred in (DEFAULT_DEEPSEEK_MODEL, "deepseek-v4-pro"):
        if preferred in text_models:
            return preferred
    if text_models:
        return text_models[0]
    if names:
        return names[0]
    return configured_id


def _uses_deepseek_chat_api(settings: Mapping[str, Any], *, base_url: str, model: str) -> bool:
    if str(settings.get("provider_preset") or "").strip().lower() == "deepseek":
        return True
    host = str(base_url or "").lower()
    name = str(model or "").lower()
    return "deepseek.com" in host or name.startswith("deepseek-v4") or name.startswith("deepseek-chat")


def finalize_remote_llm_settings(raw_remote_llm: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw_remote_llm, dict):
        raw_remote_llm = {}
    remote_llm = dict(DEFAULT_REMOTE_LLM_CONFIG)
    base_url = str(raw_remote_llm.get("base_url", "") or remote_llm["base_url"]).strip()
    if base_url:
        remote_llm["base_url"] = base_url
    raw_model = str(raw_remote_llm.get("model", "") or "").strip()
    if raw_model:
        remote_llm["model"] = migrate_remote_llm_model(raw_model)
    try:
        remote_llm["timeout_sec"] = max(15.0, float(raw_remote_llm.get("timeout_sec", remote_llm["timeout_sec"])))
    except (TypeError, ValueError):
        remote_llm["timeout_sec"] = float(DEFAULT_REMOTE_LLM_CONFIG["timeout_sec"])
    try:
        remote_llm["max_tokens"] = max(256, min(8192, int(raw_remote_llm.get("max_tokens", remote_llm["max_tokens"]))))
    except (TypeError, ValueError):
        remote_llm["max_tokens"] = int(DEFAULT_REMOTE_LLM_CONFIG["max_tokens"])
    mode, preset = resolve_remote_llm_provider_settings(raw_remote_llm)
    remote_llm["provider_mode"] = mode
    remote_llm["provider_preset"] = preset
    if preset != REMOTE_LLM_PRESET_CUSTOM:
        defaults = get_remote_llm_preset_defaults(preset)
        if defaults.get("base_url"):
            remote_llm["base_url"] = defaults["base_url"]
        if not raw_model and defaults.get("model"):
            remote_llm["model"] = defaults["model"]
    remote_llm["model"] = migrate_remote_llm_model(str(remote_llm.get("model") or ""))
    remote_llm["api_keys"] = normalize_remote_llm_api_keys(raw_remote_llm.get("api_keys"))
    return remote_llm


def get_remote_llm_settings(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from src.services.understanding_resource_service import normalize_understanding_config

    normalized = normalize_understanding_config(config)
    return dict(normalized["understanding"].get("remote_llm") or DEFAULT_REMOTE_LLM_CONFIG)


def build_remote_llm_probe_config(remote_llm: Mapping[str, Any]) -> dict[str, Any]:
    return {"understanding": {"remote_llm": dict(remote_llm or {})}}


def probe_remote_llm(config: Mapping[str, Any] | None = None, *, timeout_sec: float = 8.0) -> dict[str, Any]:
    settings = get_remote_llm_settings(config)
    return _probe_openai_compatible(settings, timeout_sec=timeout_sec)


def probe_remote_llm_draft(remote_llm: Mapping[str, Any], *, timeout_sec: float = 8.0) -> dict[str, Any]:
    settings = finalize_remote_llm_settings(remote_llm)
    return _probe_openai_compatible(settings, timeout_sec=timeout_sec)


def _probe_openai_compatible(settings: Mapping[str, Any], *, timeout_sec: float) -> dict[str, Any]:
    model = str(settings.get("model", "") or "").strip()
    provider_mode = normalize_remote_llm_provider_mode(settings.get("provider_mode", REMOTE_LLM_MODE_CLOUD))
    api_key = get_active_remote_llm_api_key(settings)
    empty = {
        "reachable": False,
        "model_available": False,
        "auth_ok": False,
        "error_code": "",
        "error": "",
        "configured_model": model,
        "available_models": [],
        "base_url": "",
    }
    try:
        base_url = _normalize_base_url(str(settings.get("base_url", "") or ""))
    except ValueError as exc:
        empty.update({"error_code": "base_url_missing", "error": str(exc)})
        return empty
    empty["base_url"] = base_url
    if not model:
        empty.update({"error_code": "model_missing", "error": "model is not configured"})
        return empty
    if provider_mode == REMOTE_LLM_MODE_CLOUD and not api_key:
        empty.update({"error_code": "cloud_api_key_required", "error": "API Key is required for cloud providers"})
        return empty
    request = urllib.request.Request(
        f"{base_url}/models",
        headers={"Accept": "application/json", **build_remote_llm_auth_headers(settings)},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout_sec))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        if exc.code in {401, 403}:
            empty.update({"error_code": "auth_failed", "error": detail[:300] or f"HTTP {exc.code}"})
            return empty
        empty.update({"error_code": "http_error", "error": detail[:300] or f"HTTP {exc.code}"})
        return empty
    except TimeoutError:
        empty.update({"error_code": "timeout", "error": "timeout"})
        return empty
    except Exception as exc:
        empty.update({"error_code": "unreachable", "error": str(exc)})
        return empty
    models = []
    for item in payload.get("data") or []:
        if isinstance(item, dict) and item.get("id"):
            models.append(str(item["id"]))
        elif isinstance(item, str):
            models.append(item)
    model_available = (not models) or (model in models)
    return {
        "reachable": True,
        "model_available": model_available,
        "auth_ok": True,
        "error_code": "" if model_available else "model_not_found",
        "error": "" if model_available else f"model {model} not in /v1/models",
        "configured_model": model,
        "available_models": models,
        "base_url": base_url,
    }


def call_remote_llm(
    *,
    system: str,
    user: str,
    config=None,
    max_tokens: int | None = None,
    temperature: float = 0.4,
    should_stop_callback=None,
) -> str:
    from src.core.understanding.base import UnderstandingStoppedError

    if should_stop_callback and should_stop_callback():
        raise UnderstandingStoppedError("LLM call stopped by user")
    settings = get_remote_llm_settings(load_config() if config is None else config)
    base_url = _normalize_base_url(str(settings.get("base_url", "") or ""))
    model = str(settings.get("model", "") or "").strip()
    if not model:
        raise RuntimeError("remote LLM model is not configured")
    timeout_sec = float(settings.get("timeout_sec", 180) or 180)
    token_limit = int(max_tokens if max_tokens is not None else settings.get("max_tokens", 4096) or 4096)
    messages = []
    if str(system or "").strip():
        messages.append({"role": "system", "content": str(system).strip()})
    messages.append({"role": "user", "content": str(user or "").strip()})
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max(256, min(8192, token_limit)),
        "temperature": float(temperature),
    }
    if _uses_deepseek_chat_api(settings, base_url=base_url, model=model):
        # V4 enables thinking by default; recap needs a clean JSON body.
        payload["thinking"] = {"type": "disabled"}
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **build_remote_llm_auth_headers(settings),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            body = json.loads(response.read().decode("utf-8"))
    except UnderstandingStoppedError:
        raise
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"remote LLM HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"remote LLM unreachable at {base_url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"remote LLM timed out after {timeout_sec:.0f}s") from exc
    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("remote LLM returned no choices")
    message = choices[0].get("message") or {}
    text = str(message.get("content", "") or "").strip()
    if not text and message.get("reasoning_content"):
        text = str(message.get("reasoning_content", "") or "").strip()
    return text
