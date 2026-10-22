"""Remote speech ASR settings (OpenAI-compatible /v1/audio/transcriptions)."""

from __future__ import annotations

from typing import Any, Mapping

REMOTE_ASR_MODE_LOCAL = "local"
REMOTE_ASR_MODE_CLOUD = "cloud"
REMOTE_ASR_PRESET_CUSTOM = "custom"
ASR_SOURCE_ID = "asr"

DEFAULT_REMOTE_ASR_CONFIG = {
    "provider_mode": REMOTE_ASR_MODE_CLOUD,
    "provider_preset": "openai",
    "base_url": "https://api.openai.com/v1",
    "model": "whisper-1",
    "api_keys": {},
    "timeout_sec": 120,
    "language": "",
}

REMOTE_ASR_PRESETS: dict[str, dict[str, str]] = {
    "openai": {
        "mode": REMOTE_ASR_MODE_CLOUD,
        "base_url": "https://api.openai.com/v1",
        "model": "whisper-1",
    },
    "groq": {
        "mode": REMOTE_ASR_MODE_CLOUD,
        "base_url": "https://api.groq.com/openai/v1",
        "model": "whisper-large-v3",
    },
    "dashscope": {
        "mode": REMOTE_ASR_MODE_CLOUD,
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-audio-3.0-asr-flash",
    },
    "siliconflow": {
        "mode": REMOTE_ASR_MODE_CLOUD,
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "FunAudioLLM/SenseVoiceSmall",
    },
    "custom": {
        "mode": REMOTE_ASR_MODE_LOCAL,
        "base_url": "http://127.0.0.1:9000/v1",
        "model": "whisper-1",
    },
}

LOCAL_ASR_PRESET_IDS = (REMOTE_ASR_PRESET_CUSTOM,)
CLOUD_ASR_PRESET_IDS = ("openai", "groq", "dashscope", "siliconflow", REMOTE_ASR_PRESET_CUSTOM)
REMOTE_ASR_API_KEY_PRESET_IDS = frozenset(CLOUD_ASR_PRESET_IDS)


def normalize_remote_asr_provider_mode(value, *, default: str = REMOTE_ASR_MODE_CLOUD) -> str:
    text = str(value or "").strip().lower()
    if text in {REMOTE_ASR_MODE_LOCAL, REMOTE_ASR_MODE_CLOUD}:
        return text
    fallback = str(default or REMOTE_ASR_MODE_CLOUD).strip().lower()
    return fallback if fallback in {REMOTE_ASR_MODE_LOCAL, REMOTE_ASR_MODE_CLOUD} else REMOTE_ASR_MODE_CLOUD


def normalize_remote_asr_provider_preset(value, *, mode: str | None = None) -> str:
    text = str(value or "").strip().lower()
    if text == REMOTE_ASR_PRESET_CUSTOM:
        return REMOTE_ASR_PRESET_CUSTOM
    if text in REMOTE_ASR_PRESETS and text != REMOTE_ASR_PRESET_CUSTOM:
        preset_mode = REMOTE_ASR_PRESETS[text]["mode"]
        if mode and normalize_remote_asr_provider_mode(mode) != preset_mode:
            return REMOTE_ASR_PRESET_CUSTOM
        return text
    return REMOTE_ASR_PRESET_CUSTOM


def get_remote_asr_preset_defaults(preset_id: str) -> dict[str, str]:
    preset = REMOTE_ASR_PRESETS.get(str(preset_id or "").strip().lower())
    if not preset:
        return {}
    return {"base_url": preset["base_url"], "model": preset["model"]}


def list_remote_asr_preset_ids(*, mode: str) -> tuple[str, ...]:
    normalized_mode = normalize_remote_asr_provider_mode(mode)
    if normalized_mode == REMOTE_ASR_MODE_LOCAL:
        return LOCAL_ASR_PRESET_IDS
    return CLOUD_ASR_PRESET_IDS


def normalize_remote_asr_api_keys(raw: Mapping[str, Any] | None) -> dict[str, str]:
    payload = dict(raw or {})
    out: dict[str, str] = {}
    for key, value in payload.items():
        preset = normalize_remote_asr_provider_preset(str(key or ""))
        text = str(value or "").strip()
        if preset in REMOTE_ASR_API_KEY_PRESET_IDS and text:
            out[preset] = text
    return out


def remote_asr_preset_supports_api_key(preset_id: str, *, mode: str | None = None) -> bool:
    preset = normalize_remote_asr_provider_preset(preset_id, mode=mode)
    if preset == REMOTE_ASR_PRESET_CUSTOM:
        return normalize_remote_asr_provider_mode(mode) == REMOTE_ASR_MODE_CLOUD
    return preset in REMOTE_ASR_API_KEY_PRESET_IDS


def get_remote_asr_api_key_for_preset(
    raw_remote_asr: Mapping[str, Any],
    preset_id: str,
    *,
    mode: str | None = None,
) -> str:
    preset = normalize_remote_asr_provider_preset(preset_id, mode=mode)
    if not remote_asr_preset_supports_api_key(preset, mode=mode):
        return ""
    api_keys = normalize_remote_asr_api_keys(raw_remote_asr.get("api_keys"))
    return str(api_keys.get(preset, "") or "").strip()


def set_remote_asr_api_key_for_preset(
    api_keys: Mapping[str, Any] | None,
    preset_id: str,
    value: str,
    *,
    mode: str | None = None,
) -> dict[str, str]:
    merged = normalize_remote_asr_api_keys(api_keys)
    preset = normalize_remote_asr_provider_preset(preset_id, mode=mode)
    if not remote_asr_preset_supports_api_key(preset, mode=mode):
        return merged
    text = str(value or "").strip()
    if text:
        merged[preset] = text
    else:
        merged.pop(preset, None)
    return merged


def get_active_remote_asr_api_key(settings: Mapping[str, Any]) -> str:
    mode = normalize_remote_asr_provider_mode(settings.get("provider_mode", REMOTE_ASR_MODE_CLOUD))
    preset = normalize_remote_asr_provider_preset(settings.get("provider_preset"), mode=mode)
    return get_remote_asr_api_key_for_preset(settings, preset, mode=mode)


def build_remote_asr_auth_headers(settings: Mapping[str, Any]) -> dict[str, str]:
    api_key = get_active_remote_asr_api_key(settings)
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def resolve_remote_asr_provider_settings(raw_remote_asr: Mapping[str, Any]) -> tuple[str, str]:
    raw = dict(raw_remote_asr or {})
    explicit_mode = raw.get("provider_mode")
    explicit_preset = raw.get("provider_preset")
    if explicit_preset:
        preset = str(explicit_preset or "").strip().lower()
        if preset in REMOTE_ASR_PRESETS and preset != REMOTE_ASR_PRESET_CUSTOM:
            preset_mode = REMOTE_ASR_PRESETS[preset]["mode"]
            mode = (
                normalize_remote_asr_provider_mode(explicit_mode, default=preset_mode)
                if explicit_mode
                else preset_mode
            )
            return mode, normalize_remote_asr_provider_preset(explicit_preset, mode=mode)
        return normalize_remote_asr_provider_mode(explicit_mode), REMOTE_ASR_PRESET_CUSTOM
    if explicit_mode:
        mode = normalize_remote_asr_provider_mode(explicit_mode)
        return mode, normalize_remote_asr_provider_preset(explicit_preset, mode=mode)
    return REMOTE_ASR_MODE_CLOUD, "openai"


def _normalize_base_url(base_url: str) -> str:
    text = str(base_url or "").strip().rstrip("/")
    if not text:
        raise ValueError("remote ASR base_url is required")
    if not text.endswith("/v1"):
        text = f"{text}/v1" if not text.endswith("/v1/") else text.rstrip("/")
    return text


def pick_available_asr_model(configured: str, available: list[str] | None) -> str:
    configured_id = str(configured or "").strip()
    names = [str(item).strip() for item in (available or []) if str(item).strip()]
    if configured_id and configured_id in names:
        return configured_id
    preferred = ("whisper-1", "whisper-large-v3", "qwen-audio-3.0-asr-flash", "qwen3-asr-flash")
    for item in preferred:
        if item in names:
            return item
    speech = [item for item in names if "whisper" in item.lower() or "asr" in item.lower()]
    if speech:
        return speech[0]
    if names:
        return names[0]
    return configured_id


def finalize_remote_asr_settings(raw_remote_asr: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw_remote_asr, dict):
        raw_remote_asr = {}
    remote_asr = dict(DEFAULT_REMOTE_ASR_CONFIG)
    base_url = str(raw_remote_asr.get("base_url", "") or remote_asr["base_url"]).strip()
    if base_url:
        remote_asr["base_url"] = base_url
    raw_model = str(raw_remote_asr.get("model", "") or "").strip()
    if raw_model:
        remote_asr["model"] = raw_model
    language = str(raw_remote_asr.get("language", "") or "").strip().lower()
    remote_asr["language"] = language if language in {"zh", "en"} else ""
    try:
        remote_asr["timeout_sec"] = max(15.0, float(raw_remote_asr.get("timeout_sec", remote_asr["timeout_sec"])))
    except (TypeError, ValueError):
        remote_asr["timeout_sec"] = float(DEFAULT_REMOTE_ASR_CONFIG["timeout_sec"])
    mode, preset = resolve_remote_asr_provider_settings(raw_remote_asr)
    remote_asr["provider_mode"] = mode
    remote_asr["provider_preset"] = preset
    if preset != REMOTE_ASR_PRESET_CUSTOM:
        defaults = get_remote_asr_preset_defaults(preset)
        if defaults.get("base_url"):
            remote_asr["base_url"] = defaults["base_url"]
        if not raw_model and defaults.get("model"):
            remote_asr["model"] = defaults["model"]
    remote_asr["api_keys"] = normalize_remote_asr_api_keys(raw_remote_asr.get("api_keys"))
    return remote_asr


def get_remote_asr_settings(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from src.services.understanding_resource_service import normalize_understanding_config

    normalized = normalize_understanding_config(config)
    return dict(normalized["understanding"].get("remote_asr") or DEFAULT_REMOTE_ASR_CONFIG)


def probe_remote_asr_draft(
    remote_asr: Mapping[str, Any],
    *,
    timeout_sec: float = 25.0,
    asr_probe: bool = True,
) -> dict[str, Any]:
    settings = finalize_remote_asr_settings(remote_asr)
    return _probe_openai_compatible(settings, timeout_sec=timeout_sec, asr_probe=asr_probe)


def _probe_openai_compatible(
    settings: Mapping[str, Any],
    *,
    timeout_sec: float = 8.0,
    asr_probe: bool = True,
) -> dict[str, Any]:
    from src.services.openai_compat_probe import (
        fetch_models_catalog,
        finalize_openai_compat_probe,
        uses_light_models_catalog,
    )

    provider_mode = normalize_remote_asr_provider_mode(settings.get("provider_mode", REMOTE_ASR_MODE_CLOUD))
    preset = str(settings.get("provider_preset") or "").strip().lower()
    api_key = get_active_remote_asr_api_key(settings)
    model = str(settings.get("model", "") or "").strip()
    cloud = provider_mode == REMOTE_ASR_MODE_CLOUD
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
    if cloud and not api_key:
        empty.update({"error_code": "cloud_api_key_required", "error": "API Key is required for cloud providers"})
        return empty

    headers = build_remote_asr_auth_headers(settings)
    catalog_timeout = min(8.0, max(2.0, float(timeout_sec) * 0.3))
    light = uses_light_models_catalog(base_url, preset)
    catalog = fetch_models_catalog(
        base_url=base_url,
        headers=headers,
        timeout_sec=catalog_timeout,
        light=light,
    )
    asr_timeout = max(8.0, float(timeout_sec) - catalog_timeout)

    def _run_asr_probe() -> dict[str, Any]:
        from src.core.asr.transcribe_remote import probe_remote_asr_transcription

        return probe_remote_asr_transcription(settings, timeout_sec=asr_timeout)

    finalized = finalize_openai_compat_probe(
        catalog=catalog,
        model=model,
        cloud=cloud,
        chat_probe=asr_probe,
        chat_probe_fn=_run_asr_probe if asr_probe else None,
        probe_label="speech",
        capability_key="asr_probed",
        capability_failed_code="asr_probe_failed",
        capability_detail_key="asr_probe_detail",
    )
    finalized["configured_model"] = model
    finalized["base_url"] = base_url
    return finalized
