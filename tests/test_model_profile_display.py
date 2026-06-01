import pytest

from src.services.model_profile_display import (
    format_active_model_display_name,
    format_text_search_model_hint,
    resolve_provider_text_language,
)


def test_resolve_provider_text_language():
    assert resolve_provider_text_language("chinese_clip_onnx") == "zh"
    assert resolve_provider_text_language("clip_onnx") == "en"
    assert resolve_provider_text_language("siglip2_onnx") == "multilingual"


def test_format_text_search_model_hint(monkeypatch):
    texts = {
        "search_text_model_hint_chinese": "中文提示",
        "search_text_model_hint_siglip2": "SigLIP2 提示",
        "search_text_model_hint_english": "English hint",
    }
    monkeypatch.setattr(
        "src.services.model_profile_display.get_active_embedding_spec",
        lambda config=None: {"provider": "chinese_clip_onnx"},
    )
    assert format_text_search_model_hint(texts) == "中文提示"
    monkeypatch.setattr(
        "src.services.model_profile_display.get_active_embedding_spec",
        lambda config=None: {"provider": "siglip2_onnx"},
    )
    assert format_text_search_model_hint(texts) == "SigLIP2 提示"


def test_format_text_search_model_hint_uses_display_name(monkeypatch):
    texts = {
        "search_text_model_hint_english": "{model} English hint",
    }
    monkeypatch.setattr(
        "src.services.model_profile_display.get_active_embedding_spec",
        lambda config=None: {"provider": "clip_onnx"},
    )
    monkeypatch.setattr(
        "src.services.model_profile_display.get_active_model_profile",
        lambda config=None: {"display_name": "CLIP ONNX", "id": "clip_onnx_default"},
    )
    assert format_text_search_model_hint(texts) == "OpenAI CLIP English hint"
    assert format_active_model_display_name() == "OpenAI CLIP"


def test_format_active_model_display_name_maps_legacy_clip_onnx_name(monkeypatch):
    monkeypatch.setattr(
        "src.services.model_profile_display.get_active_embedding_spec",
        lambda config=None: {"provider": "clip_onnx"},
    )
    monkeypatch.setattr(
        "src.services.model_profile_display.get_active_model_profile",
        lambda config=None: {"display_name": "CLIP ONNX", "id": "clip_onnx_default"},
    )
    assert format_active_model_display_name() == "OpenAI CLIP"
