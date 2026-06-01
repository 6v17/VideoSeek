from __future__ import annotations

from src.storage.config_store import get_active_embedding_spec, get_active_model_profile

_ENGLISH_ORIENTED_PROVIDERS = frozenset({"clip_onnx"})
_CHINESE_ORIENTED_PROVIDERS = frozenset({"chinese_clip_onnx"})
_MULTILINGUAL_PROVIDERS = frozenset({"siglip2_onnx"})
_CLIP_ONNX_LEGACY_DISPLAY_NAMES = frozenset({"CLIP ONNX", "clip_onnx_default"})


def resolve_provider_text_language(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized in _CHINESE_ORIENTED_PROVIDERS:
        return "zh"
    if normalized in _MULTILINGUAL_PROVIDERS:
        return "multilingual"
    if normalized in _ENGLISH_ORIENTED_PROVIDERS:
        return "en"
    return "en"


def format_active_model_display_name(config=None) -> str:
    profile = get_active_model_profile(config=config)
    spec = get_active_embedding_spec(config=config)
    provider = str(spec.get("provider") or profile.get("provider") or "").strip().lower()
    for key in ("display_name", "name", "id"):
        value = str(profile.get(key) or "").strip()
        if not value:
            continue
        if provider == "clip_onnx" and value in _CLIP_ONNX_LEGACY_DISPLAY_NAMES:
            return "OpenAI CLIP"
        return value
    if provider == "clip_onnx":
        return "OpenAI CLIP"
    return str(spec.get("model_id") or spec.get("provider") or "model").strip()


def format_active_model_search_label(config=None) -> str:
    name = format_active_model_display_name(config=config)
    spec = get_active_embedding_spec(config=config)
    dimension = int(spec.get("dimension") or 0)
    if dimension > 0:
        return f"{name} · {dimension}d"
    return name


def _format_model_text_template(template: str, config=None) -> str:
    template = str(template or "").strip()
    if not template:
        return ""
    if "{model}" not in template:
        return template
    model = format_active_model_display_name(config=config)
    return template.format(model=model)


def format_text_search_model_hint(texts, config=None) -> str:
    texts = texts or {}
    provider = str(get_active_embedding_spec(config=config).get("provider") or "").strip().lower()
    if provider in _CHINESE_ORIENTED_PROVIDERS:
        return _format_model_text_template(texts.get("search_text_model_hint_chinese", ""), config)
    if provider in _MULTILINGUAL_PROVIDERS:
        return _format_model_text_template(texts.get("search_text_model_hint_siglip2", ""), config)
    return _format_model_text_template(texts.get("search_text_model_hint_english", ""), config)
