from __future__ import annotations

import copy
import json
import os
from typing import Any, Mapping

from src.app.config import load_config, save_config
from src.app.logging_utils import get_logger
from src.core.understanding.types import (
    UnderstandingInputKind,
    UnderstandingModality,
    UnderstandingOutputKind,
    UnderstandingTask,
    normalize_enum_value,
)
from src.services.understanding_paths import (
    build_component_id,
    build_component_install_relpath,
    get_builtin_component_manifest_path,
    get_builtin_components_dir,
    get_builtin_profiles_dir,
    get_component_dir,
    get_component_manifest_path,
    get_profile_dir,
    get_profile_manifest_path,
    get_understanding_components_root,
    get_understanding_profiles_root,
    get_understanding_root,
)
from src.utils import get_configured_model_dir

logger = get_logger("understanding_resource_service")

UNDERSTANDING_COMPONENT_KIND = "understanding_component"
UNDERSTANDING_PROFILE_KIND = "understanding_profile"
UNDERSTANDING_MANIFEST_VERSION = 1
UNDERSTANDING_MANIFEST_FILENAME = "understanding_manifest.json"
PROFILE_MANIFEST_FILENAME = "profile_manifest.json"
SEARCH_MODEL_MANIFEST_FILENAME = "model_manifest.json"

DEFAULT_UNDERSTANDING_PROFILES = [
    {
        "id": "vision_baseline_v1",
        "display_name": "视觉基础版",
        "profile_dir": "vision_baseline_v1",
        "enabled": True,
    }
]

_CUSTOM_PROMPT_MAX_CHARS = 4000

DEFAULT_REMOTE_VLM_CONFIG = {
    "provider_mode": "local",
    "provider_preset": "lm_studio",
    "base_url": "http://127.0.0.1:1234/v1",
    "model": "qwen3-vl-8b-instruct",
    "api_keys": {},
    "caption_language": "zh",
    "understanding_mode": "motion",
    "use_custom_prompts": False,
    "custom_caption_prompt": "",
    "custom_tag_prompt": "",
    "custom_description_prompt": "",
    "custom_motion_prompt": "",
    "custom_summary_prompt": "",
    "prompt": (
        "为这一视频帧提取简洁中文标签。只输出 JSON："
        '{"tags":["标签1","标签2"]}。'
        "标签覆盖人物/角色、场景地点、可见物体、动作、氛围风格；"
        "每条2-8字，不要句子，不要解释，不要 markdown。"
    ),
    "timeout_sec": 120,
    "max_tokens": 192,
    "concurrency": 2,
}

REMOTE_VLM_MODE_LOCAL = "local"
REMOTE_VLM_MODE_CLOUD = "cloud"
REMOTE_VLM_PRESET_CUSTOM = "custom"

REMOTE_VLM_PRESETS: dict[str, dict[str, str]] = {
    "lm_studio": {
        "mode": REMOTE_VLM_MODE_LOCAL,
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "qwen3-vl-8b-instruct",
    },
    "ollama": {
        "mode": REMOTE_VLM_MODE_LOCAL,
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen3-vl-8b-instruct",
    },
    "openai": {
        "mode": REMOTE_VLM_MODE_CLOUD,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "dashscope": {
        "mode": REMOTE_VLM_MODE_CLOUD,
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-max",
    },
    "siliconflow": {
        "mode": REMOTE_VLM_MODE_CLOUD,
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-VL-32B-Instruct",
    },
}

LOCAL_VLM_PRESET_IDS = ("lm_studio", "ollama", REMOTE_VLM_PRESET_CUSTOM)
CLOUD_VLM_PRESET_IDS = ("openai", "dashscope", "siliconflow", REMOTE_VLM_PRESET_CUSTOM)
REMOTE_VLM_API_KEY_PRESET_IDS = frozenset(CLOUD_VLM_PRESET_IDS)

CAPTION_LANGUAGE_ZH = "zh"
CAPTION_LANGUAGE_EN = "en"
SUPPORTED_CAPTION_LANGUAGES = {CAPTION_LANGUAGE_ZH, CAPTION_LANGUAGE_EN}

UNDERSTANDING_MODE_TAGS = "tags"
UNDERSTANDING_MODE_SUMMARY = "summary"
UNDERSTANDING_MODE_MOTION = "motion"
SUPPORTED_UNDERSTANDING_MODES = {
    UNDERSTANDING_MODE_TAGS,
    UNDERSTANDING_MODE_SUMMARY,
    UNDERSTANDING_MODE_MOTION,
}
SPLIT_UNDERSTANDING_MODES = (
    UNDERSTANDING_MODE_TAGS,
    UNDERSTANDING_MODE_SUMMARY,
    UNDERSTANDING_MODE_MOTION,
)
# Recap / VO / FCPXML uses a separate LLM job (see recap_service), not these vision modes.

# Tag mode: chunk tags only.
TAG_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: (
        "为这一视频帧提取简洁中文标签。只输出 JSON："
        '{"tags":["标签1","标签2"]}。'
        "标签覆盖人物/角色、场景地点、可见物体、动作、氛围风格；"
        "每条2-8字，不要句子，不要解释，不要 markdown。"
    ),
    CAPTION_LANGUAGE_EN: (
        "Extract concise English tags for this video frame. "
        'Output JSON only: {"tags":["tag1","tag2"]}. '
        "Cover people/characters, place/setting, visible objects, actions, mood/style. "
        "Use short tags (1-3 words). No sentences, no explanation, no markdown."
    ),
}
# Keep old name as alias so existing imports/tests keep working.
CAPTION_LANGUAGE_PROMPTS = TAG_LANGUAGE_PROMPTS

# Summary mode: chunk descriptions (then whole-video summary).
DESCRIPTION_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: (
        "用一两句简洁的中文描述这一视频帧的画面内容。"
        "只写可见内容，不要列举分析过程，不要 markdown。"
    ),
    CAPTION_LANGUAGE_EN: (
        "Describe this video frame in one or two concise sentences. "
        "Only what is visible. No analysis steps, no markdown."
    ),
}
# Motion mode: stitched earlier/later frames from the same chunk. Describe change only; optional tags.
MOTION_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: (
        "这是一张视频时间片段拼接图。\n"
        "\n"
        "左侧帧早于右侧帧，图片中有时间标注。\n"
        "请比较两帧之间的变化，只描述该时间段内实际可见的变化。\n"
        "\n"
        "要求：\n"
        "1. 用2-4句中文描述发生了什么变化。\n"
        "2. 描述可见的人物、动作、物体、环境、表情和镜头变化。\n"
        "3. 可以判断镜头类型或片段用途（如对话、动作、场景展示、情绪反应、过渡），"
        "但不要编造剧情、人物关系、背景原因或画外信息。\n"
        "4. 不要输出故事总结，不要 Markdown。\n"
        "\n"
        "最后，如果可以提取，请单独输出 JSON：\n"
        '{"tags":["人物/动作/场景/镜头/情绪等短标签"]}'
    ),
    CAPTION_LANGUAGE_EN: (
        "This is a stitched image of two frames from the same video span.\n"
        "\n"
        "The left frame is earlier than the right. The image is time-labeled.\n"
        "Compare the two frames and describe only changes that are actually visible in this span.\n"
        "\n"
        "Requirements:\n"
        "1. Describe what changed in 2-4 English sentences.\n"
        "2. Cover visible people, actions, objects, setting, expressions, and camera change.\n"
        "3. You may label the shot type or beat (dialogue, action, establishing, reaction, transition), "
        "but do not invent plot, relationships, off-screen causes, or unseen information.\n"
        "4. No story summary. No markdown.\n"
        "\n"
        "Finally, if you can extract them, output JSON on its own:\n"
        '{"tags":["short tags for people/action/scene/shot/emotion"]}'
    ),
}
VIDEO_SUMMARY_LANGUAGE_PROMPTS = {
    CAPTION_LANGUAGE_ZH: (
        "以下是一个视频按时间顺序各段的画面描述。请用一段简洁的中文总结整个视频的主要内容、"
        "情节或主题，不要逐段复述，不要输出分析过程。"
    ),
    CAPTION_LANGUAGE_EN: (
        "Below are chronological segment descriptions of a video. "
        "Write one concise paragraph summarizing the overall content, story, or theme. "
        "Do not repeat each segment line by line."
    ),
}


def normalize_caption_language(value, *, default: str = CAPTION_LANGUAGE_ZH) -> str:
    text = str(value or "").strip().lower()
    if text in SUPPORTED_CAPTION_LANGUAGES:
        return text
    fallback = str(default or CAPTION_LANGUAGE_ZH).strip().lower()
    return fallback if fallback in SUPPORTED_CAPTION_LANGUAGES else CAPTION_LANGUAGE_ZH


def normalize_understanding_mode(value, *, default: str = UNDERSTANDING_MODE_TAGS) -> str:
    text = str(value or "").strip().lower()
    if text in SUPPORTED_UNDERSTANDING_MODES:
        return text
    # Accept a few aliases from older UI copy.
    if text in {"tag", "label", "labels"}:
        return UNDERSTANDING_MODE_TAGS
    if text in {"caption", "captions", "describe", "description", "descriptions"}:
        return UNDERSTANDING_MODE_SUMMARY
    if text in {"motion", "movement", "change", "changes"}:
        return UNDERSTANDING_MODE_MOTION
    fallback = str(default or UNDERSTANDING_MODE_TAGS).strip().lower()
    return fallback if fallback in SUPPORTED_UNDERSTANDING_MODES else UNDERSTANDING_MODE_TAGS


def get_tag_prompt_for_language(language: str) -> str:
    return TAG_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def get_caption_prompt_for_language(language: str) -> str:
    # Historical name: used as the chunk prompt for the active product path.
    # Prefer get_tag_prompt_for_language / get_description_prompt_for_language.
    return get_tag_prompt_for_language(language)


def get_description_prompt_for_language(language: str) -> str:
    return DESCRIPTION_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def get_video_summary_prompt_for_language(language: str) -> str:
    return VIDEO_SUMMARY_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def get_motion_prompt_for_language(language: str) -> str:
    return MOTION_LANGUAGE_PROMPTS[normalize_caption_language(language)]


def normalize_use_custom_prompts(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def normalize_custom_prompt_text(value) -> str:
    text = str(value or "").strip()
    if len(text) > _CUSTOM_PROMPT_MAX_CHARS:
        return text[:_CUSTOM_PROMPT_MAX_CHARS]
    return text


def resolve_tag_prompt(settings: Mapping[str, Any] | None) -> str:
    raw = dict(settings or {})
    language = normalize_caption_language(raw.get("caption_language", CAPTION_LANGUAGE_ZH))
    custom = normalize_custom_prompt_text(raw.get("custom_tag_prompt") or raw.get("custom_caption_prompt"))
    if normalize_use_custom_prompts(raw.get("use_custom_prompts")) and custom:
        return custom
    return get_tag_prompt_for_language(language)


def resolve_description_prompt(settings: Mapping[str, Any] | None) -> str:
    raw = dict(settings or {})
    language = normalize_caption_language(raw.get("caption_language", CAPTION_LANGUAGE_ZH))
    custom = normalize_custom_prompt_text(raw.get("custom_description_prompt"))
    if normalize_use_custom_prompts(raw.get("use_custom_prompts")) and custom:
        return custom
    return get_description_prompt_for_language(language)


def resolve_motion_prompt(settings: Mapping[str, Any] | None) -> str:
    raw = dict(settings or {})
    language = normalize_caption_language(raw.get("caption_language", CAPTION_LANGUAGE_ZH))
    custom = normalize_custom_prompt_text(raw.get("custom_motion_prompt"))
    if normalize_use_custom_prompts(raw.get("use_custom_prompts")) and custom:
        return custom
    return get_motion_prompt_for_language(language)


def resolve_caption_prompt(settings: Mapping[str, Any] | None) -> str:
    """Chunk VLM prompt for the active understanding mode."""
    raw = dict(settings or {})
    mode = normalize_understanding_mode(raw.get("understanding_mode", UNDERSTANDING_MODE_TAGS))
    if mode == UNDERSTANDING_MODE_SUMMARY:
        return resolve_description_prompt(raw)
    if mode == UNDERSTANDING_MODE_MOTION:
        return resolve_motion_prompt(raw)
    return resolve_tag_prompt(raw)


def resolve_video_summary_prompt(settings: Mapping[str, Any] | None) -> str:
    raw = dict(settings or {})
    language = normalize_caption_language(raw.get("caption_language", CAPTION_LANGUAGE_ZH))
    custom = normalize_custom_prompt_text(raw.get("custom_summary_prompt"))
    if normalize_use_custom_prompts(raw.get("use_custom_prompts")) and custom:
        return custom
    return get_video_summary_prompt_for_language(language)


def _normalize_vlm_base_url_for_compare(base_url: str) -> str:
    text = str(base_url or "").strip().rstrip("/").lower()
    if not text:
        return ""
    if text.endswith("/v1"):
        return text
    return f"{text}/v1"


def normalize_remote_vlm_provider_mode(value, *, default: str = REMOTE_VLM_MODE_LOCAL) -> str:
    text = str(value or "").strip().lower()
    if text in {REMOTE_VLM_MODE_LOCAL, REMOTE_VLM_MODE_CLOUD}:
        return text
    fallback = str(default or REMOTE_VLM_MODE_LOCAL).strip().lower()
    return fallback if fallback in {REMOTE_VLM_MODE_LOCAL, REMOTE_VLM_MODE_CLOUD} else REMOTE_VLM_MODE_LOCAL


def normalize_remote_vlm_provider_preset(value, *, mode: str | None = None) -> str:
    text = str(value or "").strip().lower()
    if text == REMOTE_VLM_PRESET_CUSTOM:
        return REMOTE_VLM_PRESET_CUSTOM
    if text in REMOTE_VLM_PRESETS:
        preset_mode = REMOTE_VLM_PRESETS[text]["mode"]
        if mode and preset_mode != mode:
            return REMOTE_VLM_PRESET_CUSTOM
        return text
    return REMOTE_VLM_PRESET_CUSTOM


def resolve_remote_vlm_provider_settings(raw_remote_vlm: Mapping[str, Any]) -> tuple[str, str]:
    raw = dict(raw_remote_vlm or {})
    base_url = str(raw.get("base_url", "") or "").strip()
    has_cloud_api_key = bool(normalize_remote_vlm_api_keys(raw.get("api_keys")))
    explicit_mode = str(raw.get("provider_mode", "") or "").strip().lower()
    explicit_preset = str(raw.get("provider_preset", "") or "").strip().lower()
    has_explicit_mode = "provider_mode" in raw and bool(explicit_mode)
    has_explicit_preset = "provider_preset" in raw and bool(explicit_preset)

    if has_explicit_preset and explicit_preset in REMOTE_VLM_PRESETS:
        preset_mode = REMOTE_VLM_PRESETS[explicit_preset]["mode"]
        mode = normalize_remote_vlm_provider_mode(explicit_mode, default=preset_mode) if has_explicit_mode else preset_mode
        return mode, explicit_preset

    if has_explicit_mode and has_explicit_preset and explicit_preset == REMOTE_VLM_PRESET_CUSTOM:
        return normalize_remote_vlm_provider_mode(explicit_mode), REMOTE_VLM_PRESET_CUSTOM

    normalized_url = _normalize_vlm_base_url_for_compare(base_url)
    for preset_id, preset in REMOTE_VLM_PRESETS.items():
        if normalized_url and normalized_url == _normalize_vlm_base_url_for_compare(preset["base_url"]):
            return preset["mode"], preset_id

    if has_cloud_api_key or (
        normalized_url.startswith("https://")
        and "127.0.0.1" not in normalized_url
        and "localhost" not in normalized_url
    ):
        return REMOTE_VLM_MODE_CLOUD, REMOTE_VLM_PRESET_CUSTOM

    if normalized_url:
        return REMOTE_VLM_MODE_LOCAL, REMOTE_VLM_PRESET_CUSTOM

    if has_explicit_mode or has_explicit_preset:
        mode = normalize_remote_vlm_provider_mode(explicit_mode)
        preset = normalize_remote_vlm_provider_preset(explicit_preset, mode=mode)
        return mode, preset

    return REMOTE_VLM_MODE_LOCAL, "lm_studio"


def get_remote_vlm_preset_defaults(preset_id: str) -> dict[str, str]:
    preset = REMOTE_VLM_PRESETS.get(str(preset_id or "").strip().lower())
    if not preset:
        return {}
    return {"base_url": preset["base_url"], "model": preset["model"]}


def list_remote_vlm_preset_ids(*, mode: str) -> tuple[str, ...]:
    normalized_mode = normalize_remote_vlm_provider_mode(mode)
    if normalized_mode == REMOTE_VLM_MODE_CLOUD:
        return CLOUD_VLM_PRESET_IDS
    return LOCAL_VLM_PRESET_IDS


def normalize_remote_vlm_api_keys(raw: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        preset = normalize_remote_vlm_provider_preset(str(key or ""))
        if preset not in REMOTE_VLM_API_KEY_PRESET_IDS:
            continue
        text = str(value or "").strip()
        if text:
            cleaned[preset] = text
    return cleaned


def remote_vlm_preset_supports_api_key(preset_id: str, *, mode: str | None = None) -> bool:
    preset = normalize_remote_vlm_provider_preset(preset_id, mode=mode)
    if preset not in REMOTE_VLM_API_KEY_PRESET_IDS:
        return False
    if preset == REMOTE_VLM_PRESET_CUSTOM:
        return normalize_remote_vlm_provider_mode(mode) == REMOTE_VLM_MODE_CLOUD
    return REMOTE_VLM_PRESETS.get(preset, {}).get("mode") == REMOTE_VLM_MODE_CLOUD


def get_remote_vlm_api_key_for_preset(
    raw_remote_vlm: Mapping[str, Any],
    preset_id: str,
    *,
    mode: str | None = None,
) -> str:
    preset = normalize_remote_vlm_provider_preset(preset_id, mode=mode)
    if not remote_vlm_preset_supports_api_key(preset, mode=mode):
        return ""
    api_keys = normalize_remote_vlm_api_keys(raw_remote_vlm.get("api_keys"))
    return api_keys.get(preset, "")


def set_remote_vlm_api_key_for_preset(
    api_keys: Mapping[str, Any] | None,
    preset_id: str,
    api_key: str,
    *,
    mode: str | None = None,
) -> dict[str, str]:
    merged = normalize_remote_vlm_api_keys(api_keys)
    preset = normalize_remote_vlm_provider_preset(preset_id, mode=mode)
    if not remote_vlm_preset_supports_api_key(preset, mode=mode):
        return merged
    text = str(api_key or "").strip()
    if text:
        merged[preset] = text
    else:
        merged.pop(preset, None)
    return merged


def get_active_remote_vlm_api_key(settings: Mapping[str, Any]) -> str:
    mode = normalize_remote_vlm_provider_mode(settings.get("provider_mode", REMOTE_VLM_MODE_LOCAL))
    preset = normalize_remote_vlm_provider_preset(
        settings.get("provider_preset"),
        mode=mode,
    )
    return get_remote_vlm_api_key_for_preset(settings, preset, mode=mode)


def resolve_remote_vlm_caption_language(raw_remote_vlm: Mapping[str, Any]) -> str:
    explicit = str(raw_remote_vlm.get("caption_language", "") or "").strip()
    if explicit:
        return normalize_caption_language(explicit)
    prompt = str(raw_remote_vlm.get("prompt", "") or "").strip()
    if prompt == CAPTION_LANGUAGE_PROMPTS[CAPTION_LANGUAGE_EN] or prompt.startswith("Describe this video frame") or (
        "Extract concise English tags" in prompt
    ):
        return CAPTION_LANGUAGE_EN
    if prompt == CAPTION_LANGUAGE_PROMPTS[CAPTION_LANGUAGE_ZH] or any(
        token in prompt for token in ("中文", "视频帧", "标签")
    ):
        return CAPTION_LANGUAGE_ZH
    return CAPTION_LANGUAGE_EN if prompt and ("Describe" in prompt or "Extract concise English tags" in prompt) else CAPTION_LANGUAGE_ZH


def finalize_remote_vlm_settings(raw_remote_vlm: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw_remote_vlm, dict):
        raw_remote_vlm = {}
    remote_vlm = dict(DEFAULT_REMOTE_VLM_CONFIG)
    base_url = str(raw_remote_vlm.get("base_url", "") or remote_vlm["base_url"]).strip()
    if base_url:
        remote_vlm["base_url"] = base_url
    model = str(raw_remote_vlm.get("model", "") or remote_vlm["model"]).strip()
    if model:
        remote_vlm["model"] = model
    language = resolve_remote_vlm_caption_language(raw_remote_vlm)
    remote_vlm["caption_language"] = language
    remote_vlm["understanding_mode"] = normalize_understanding_mode(
        raw_remote_vlm.get("understanding_mode", DEFAULT_REMOTE_VLM_CONFIG["understanding_mode"])
    )
    remote_vlm["use_custom_prompts"] = normalize_use_custom_prompts(
        raw_remote_vlm.get("use_custom_prompts", DEFAULT_REMOTE_VLM_CONFIG["use_custom_prompts"])
    )
    # custom_caption_prompt kept for backward compatibility (maps to tag prompt).
    legacy_caption = normalize_custom_prompt_text(raw_remote_vlm.get("custom_caption_prompt", ""))
    remote_vlm["custom_tag_prompt"] = normalize_custom_prompt_text(
        raw_remote_vlm.get("custom_tag_prompt", "") or legacy_caption
    )
    remote_vlm["custom_description_prompt"] = normalize_custom_prompt_text(
        raw_remote_vlm.get("custom_description_prompt", "")
    )
    remote_vlm["custom_summary_prompt"] = normalize_custom_prompt_text(
        raw_remote_vlm.get("custom_summary_prompt", "")
    )
    remote_vlm["custom_motion_prompt"] = normalize_custom_prompt_text(
        raw_remote_vlm.get("custom_motion_prompt", "")
    )
    remote_vlm["custom_caption_prompt"] = remote_vlm["custom_tag_prompt"]
    remote_vlm["prompt"] = resolve_caption_prompt(remote_vlm)
    try:
        remote_vlm["timeout_sec"] = max(5.0, float(raw_remote_vlm.get("timeout_sec", remote_vlm["timeout_sec"])))
    except (TypeError, ValueError):
        remote_vlm["timeout_sec"] = float(DEFAULT_REMOTE_VLM_CONFIG["timeout_sec"])
    try:
        remote_vlm["max_tokens"] = max(16, min(512, int(raw_remote_vlm.get("max_tokens", remote_vlm["max_tokens"]))))
    except (TypeError, ValueError):
        remote_vlm["max_tokens"] = int(DEFAULT_REMOTE_VLM_CONFIG["max_tokens"])
    try:
        remote_vlm["concurrency"] = max(1, min(4, int(raw_remote_vlm.get("concurrency", remote_vlm.get("concurrency", 2)))))
    except (TypeError, ValueError):
        remote_vlm["concurrency"] = int(DEFAULT_REMOTE_VLM_CONFIG["concurrency"])
    mode, preset = resolve_remote_vlm_provider_settings(raw_remote_vlm)
    remote_vlm["provider_mode"] = mode
    remote_vlm["provider_preset"] = preset
    if preset != REMOTE_VLM_PRESET_CUSTOM:
        defaults = get_remote_vlm_preset_defaults(preset)
        if defaults.get("base_url"):
            # Prefer the preset endpoint unless the user explicitly overrode base_url
            # while staying on a named preset (legacy configs may still store defaults).
            raw_base = str(raw_remote_vlm.get("base_url", "") or "").strip()
            if not raw_base or raw_base == str(DEFAULT_REMOTE_VLM_CONFIG.get("base_url") or "").strip():
                remote_vlm["base_url"] = defaults["base_url"]
            else:
                remote_vlm["base_url"] = raw_base
        raw_model = str(raw_remote_vlm.get("model", "") or "").strip()
        if raw_model:
            remote_vlm["model"] = raw_model
        elif defaults.get("model"):
            remote_vlm["model"] = defaults["model"]

    remote_vlm["api_keys"] = normalize_remote_vlm_api_keys(raw_remote_vlm.get("api_keys"))
    return remote_vlm


def build_remote_vlm_auth_headers(settings: Mapping[str, Any]) -> dict[str, str]:
    api_key = get_active_remote_vlm_api_key(settings)
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}

DEFAULT_UNDERSTANDING_CONFIG = {
    "active_profile": "vision_baseline_v1",
    "profiles": list(DEFAULT_UNDERSTANDING_PROFILES),
    "remote_vlm": dict(DEFAULT_REMOTE_VLM_CONFIG),
    "remote_llm": {},
    "remote_asr": {},
}


class UnderstandingManifestError(ValueError):
    """Raised when an understanding manifest fails validation."""


def _require_mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise UnderstandingManifestError(f"{field_name} must be an object")
    return dict(value)


def _require_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise UnderstandingManifestError(f"{field_name} is required")
    return text


def _read_json_file(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise UnderstandingManifestError(f"{path}: manifest root must be a JSON object")
    return payload


def validate_component_manifest(
    manifest: Mapping[str, Any],
    *,
    component_dir: str | None = None,
) -> dict[str, Any]:
    data = _require_mapping(manifest, "manifest")
    kind = _require_text(data.get("kind"), "kind")
    if kind != UNDERSTANDING_COMPONENT_KIND:
        raise UnderstandingManifestError(f"kind must be {UNDERSTANDING_COMPONENT_KIND!r}, got {kind!r}")

    manifest_version = data.get("manifest_version")
    try:
        if int(manifest_version) != UNDERSTANDING_MANIFEST_VERSION:
            raise UnderstandingManifestError(
                f"manifest_version must be {UNDERSTANDING_MANIFEST_VERSION}, got {manifest_version!r}"
            )
    except (TypeError, ValueError) as exc:
        raise UnderstandingManifestError("manifest_version must be an integer") from exc

    modality = normalize_enum_value(UnderstandingModality, data.get("modality"), "modality")
    task = normalize_enum_value(UnderstandingTask, data.get("task"), "task")
    model_id = _require_text(data.get("model_id"), "model_id")
    component_id = _require_text(data.get("id"), "id")
    expected_id = build_component_id(modality, task, model_id)
    if component_id != expected_id:
        raise UnderstandingManifestError(f"id must be {expected_id!r}, got {component_id!r}")

    install_relpath = _require_text(data.get("install_relpath"), "install_relpath").replace("\\", "/")
    expected_relpath = build_component_install_relpath(modality, task, model_id).replace("\\", "/")
    if install_relpath != expected_relpath:
        raise UnderstandingManifestError(
            f"install_relpath must be {expected_relpath!r}, got {install_relpath!r}"
        )

    normalize_enum_value(UnderstandingInputKind, data.get("input_kind"), "input_kind")
    normalize_enum_value(UnderstandingOutputKind, data.get("output_kind"), "output_kind")

    engine = _require_mapping(data.get("engine"), "engine")
    _require_text(engine.get("registry_key"), "engine.registry_key")

    required_files = data.get("required_files")
    delivery = str(data.get("delivery", "local") or "local").strip().lower()
    if not isinstance(required_files, list):
        raise UnderstandingManifestError("required_files must be a list")
    normalized_required = [_require_text(name, f"required_files[{index}]") for index, name in enumerate(required_files)]
    if delivery != "remote" and not normalized_required:
        raise UnderstandingManifestError("required_files must be a non-empty list")

    if component_dir:
        missing = [
            name
            for name in normalized_required
            if not os.path.isfile(os.path.join(component_dir, name))
            or os.path.getsize(os.path.join(component_dir, name)) <= 0
        ]
        if missing:
            raise UnderstandingManifestError(
                f"missing required files under {component_dir}: {', '.join(missing)}"
            )

    return dict(data)


def validate_profile_manifest(
    manifest: Mapping[str, Any],
    *,
    profile_dir: str | None = None,
) -> dict[str, Any]:
    data = _require_mapping(manifest, "manifest")
    kind = _require_text(data.get("kind"), "kind")
    if kind != UNDERSTANDING_PROFILE_KIND:
        raise UnderstandingManifestError(f"kind must be {UNDERSTANDING_PROFILE_KIND!r}, got {kind!r}")

    manifest_version = data.get("manifest_version")
    try:
        if int(manifest_version) != UNDERSTANDING_MANIFEST_VERSION:
            raise UnderstandingManifestError(
                f"manifest_version must be {UNDERSTANDING_MANIFEST_VERSION}, got {manifest_version!r}"
            )
    except (TypeError, ValueError) as exc:
        raise UnderstandingManifestError("manifest_version must be an integer") from exc

    profile_id = _require_text(data.get("id"), "id")
    install_relpath = _require_text(data.get("install_relpath"), "install_relpath").replace("\\", "/")
    expected_relpath = f"profiles/{profile_id}"
    if install_relpath != expected_relpath:
        raise UnderstandingManifestError(
            f"install_relpath must be {expected_relpath!r}, got {install_relpath!r}"
        )

    requires = _require_mapping(data.get("requires"), "requires")
    components = requires.get("components")
    if not isinstance(components, list) or not components:
        raise UnderstandingManifestError("requires.components must be a non-empty list")
    for index, component_id in enumerate(components):
        _require_text(component_id, f"requires.components[{index}]")

    optional_components = requires.get("optional_components", [])
    if optional_components is None:
        optional_components = []
    if not isinstance(optional_components, list):
        raise UnderstandingManifestError("requires.optional_components must be a list")
    for index, component_id in enumerate(optional_components):
        _require_text(component_id, f"requires.optional_components[{index}]")

    pipeline = data.get("pipeline")
    if not isinstance(pipeline, list) or not pipeline:
        raise UnderstandingManifestError("pipeline must be a non-empty list")
    for index, step in enumerate(pipeline):
        step_payload = _require_mapping(step, f"pipeline[{index}]")
        _require_text(step_payload.get("step"), f"pipeline[{index}].step")
        _require_text(step_payload.get("component"), f"pipeline[{index}].component")

    if profile_dir and profile_id != os.path.basename(os.path.normpath(profile_dir)):
        raise UnderstandingManifestError(
            f"profile id {profile_id!r} does not match directory {profile_dir!r}"
        )

    return dict(data)


def normalize_understanding_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(config or load_config())
    raw_understanding = cfg.get("understanding")
    if not isinstance(raw_understanding, dict):
        raw_understanding = {}

    profiles = raw_understanding.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        profiles = copy.deepcopy(DEFAULT_UNDERSTANDING_PROFILES)

    normalized_profiles = []
    seen_ids: set[str] = set()
    for item in profiles:
        if not isinstance(item, dict):
            continue
        profile_id = str(item.get("id", "") or "").strip()
        if not profile_id or profile_id in seen_ids:
            continue
        profile_dir = str(item.get("profile_dir", "") or profile_id).strip() or profile_id
        normalized_profiles.append(
            {
                "id": profile_id,
                "display_name": str(item.get("display_name", "") or profile_id).strip() or profile_id,
                "profile_dir": profile_dir,
                "enabled": bool(item.get("enabled", True)),
            }
        )
        seen_ids.add(profile_id)

    if not normalized_profiles:
        normalized_profiles = copy.deepcopy(DEFAULT_UNDERSTANDING_PROFILES)

    active_profile = str(raw_understanding.get("active_profile", "") or "").strip()
    if not active_profile:
        active_profile = normalized_profiles[0]["id"]
    if not any(item["id"] == active_profile for item in normalized_profiles):
        active_profile = normalized_profiles[0]["id"]

    raw_remote_vlm = raw_understanding.get("remote_vlm")
    remote_vlm = finalize_remote_vlm_settings(raw_remote_vlm)
    from src.services.llm_settings import DEFAULT_REMOTE_LLM_CONFIG, finalize_remote_llm_settings

    remote_llm = finalize_remote_llm_settings(raw_understanding.get("remote_llm"))
    from src.services.asr_settings import DEFAULT_REMOTE_ASR_CONFIG, finalize_remote_asr_settings

    remote_asr = finalize_remote_asr_settings(raw_understanding.get("remote_asr"))

    understanding = {
        "active_profile": active_profile,
        "profiles": normalized_profiles,
        "remote_vlm": remote_vlm,
        "remote_llm": remote_llm or dict(DEFAULT_REMOTE_LLM_CONFIG),
        "remote_asr": remote_asr or dict(DEFAULT_REMOTE_ASR_CONFIG),
    }
    cfg["understanding"] = understanding
    return cfg


def ensure_understanding_config(config: Mapping[str, Any] | None = None, *, persist: bool = False) -> dict[str, Any]:
    normalized = normalize_understanding_config(config)
    if persist:
        save_config(normalized)
    return normalized


def get_understanding_profiles(config: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    return list(normalize_understanding_config(config)["understanding"]["profiles"])


def get_active_understanding_profile_id(config: Mapping[str, Any] | None = None) -> str:
    return str(normalize_understanding_config(config)["understanding"]["active_profile"])


def _resolve_model_dir(model_dir: str | None) -> str:
    resolved = str(model_dir or get_configured_model_dir() or "").strip()
    if not resolved:
        raise ValueError("model_dir is not configured")
    return os.path.normpath(resolved)


def discover_component_manifest_paths(model_dir: str | None = None) -> list[str]:
    components_root = get_understanding_components_root(model_dir)
    if not os.path.isdir(components_root):
        return []
    found: list[str] = []
    for current_root, _dirs, files in os.walk(components_root):
        if UNDERSTANDING_MANIFEST_FILENAME in files:
            found.append(os.path.join(current_root, UNDERSTANDING_MANIFEST_FILENAME))
    return sorted(found)


def scan_understanding_components(model_dir: str | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for manifest_path in discover_component_manifest_paths(model_dir):
        component_dir = os.path.dirname(manifest_path)
        entry: dict[str, Any] = {
            "manifest_path": manifest_path,
            "component_dir": component_dir,
            "installed": False,
            "missing_files": [],
            "error": "",
        }
        try:
            manifest = _read_json_file(manifest_path)
            validated = validate_component_manifest(manifest, component_dir=component_dir)
            entry.update(
                {
                    "id": validated["id"],
                    "modality": validated["modality"],
                    "task": validated["task"],
                    "model_id": validated["model_id"],
                    "display_name": validated.get("display_name", validated["id"]),
                    "installed": True,
                    "manifest": validated,
                }
            )
        except Exception as exc:
            entry["error"] = str(exc)
            try:
                manifest = _read_json_file(manifest_path)
                entry["id"] = str(manifest.get("id", "") or "")
            except Exception:
                entry["id"] = ""
        results.append(entry)
    return results


def _iter_builtin_profile_manifest_paths() -> list[str]:
    profiles_root = get_builtin_profiles_dir()
    if not os.path.isdir(profiles_root):
        return []
    found: list[str] = []
    for name in sorted(os.listdir(profiles_root)):
        manifest_path = os.path.join(profiles_root, name, PROFILE_MANIFEST_FILENAME)
        if os.path.isfile(manifest_path):
            found.append(manifest_path)
    return found


def _iter_builtin_component_manifest_paths() -> list[str]:
    components_root = get_builtin_components_dir()
    if not os.path.isdir(components_root):
        return []
    found: list[str] = []
    for current_root, _dirs, files in os.walk(components_root):
        if UNDERSTANDING_MANIFEST_FILENAME in files:
            found.append(os.path.join(current_root, UNDERSTANDING_MANIFEST_FILENAME))
    return sorted(found)


def get_remote_vlm_settings(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_understanding_config(config)
    return dict(normalized["understanding"].get("remote_vlm") or DEFAULT_REMOTE_VLM_CONFIG)


def get_remote_vlm_concurrency(config: Mapping[str, Any] | None = None) -> int:
    settings = get_remote_vlm_settings(config)
    try:
        return max(1, min(4, int(settings.get("concurrency", DEFAULT_REMOTE_VLM_CONFIG["concurrency"]))))
    except (TypeError, ValueError):
        return int(DEFAULT_REMOTE_VLM_CONFIG["concurrency"])


def probe_remote_vlm(config: Mapping[str, Any] | None = None, *, timeout_sec: float = 3.0) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    settings = get_remote_vlm_settings(config)
    base_url = str(settings.get("base_url", "") or "").strip().rstrip("/")
    model = str(settings.get("model", "") or "").strip()
    provider_mode = normalize_remote_vlm_provider_mode(settings.get("provider_mode", REMOTE_VLM_MODE_LOCAL))
    api_key = get_active_remote_vlm_api_key(settings)

    def _result(**payload: Any) -> dict[str, Any]:
        out = dict(payload)
        out.setdefault("base_url", base_url)
        out.setdefault("configured_model", model)
        out.setdefault("available_models", [])
        return out

    if not base_url:
        return _result(
            reachable=False,
            model_available=False,
            auth_ok=False,
            error_code="base_url_missing",
            error="base_url is not configured",
        )
    if not model:
        return _result(
            reachable=False,
            model_available=False,
            auth_ok=False,
            error_code="model_missing",
            error="model is not configured",
            configured_model="",
        )
    if provider_mode == REMOTE_VLM_MODE_CLOUD and not api_key:
        return _result(
            reachable=False,
            model_available=False,
            auth_ok=False,
            error_code="cloud_api_key_required",
            error="API Key is required for cloud providers",
        )
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1" if not base_url.endswith("/v1/") else base_url.rstrip("/")

    request = urllib.request.Request(
        f"{base_url}/models",
        headers={"Accept": "application/json", **build_remote_vlm_auth_headers(settings)},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout_sec))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        if exc.code in {401, 403}:
            return _result(
                reachable=False,
                model_available=False,
                auth_ok=False,
                error_code="auth_failed",
                error=f"HTTP {exc.code}: API Key invalid or unauthorized",
                http_status=int(exc.code),
                http_detail=detail[:240],
            )
        return _result(
            reachable=False,
            model_available=False,
            auth_ok=False,
            error_code="http_error",
            error=f"HTTP {exc.code}: {detail[:240] or exc.reason}",
            http_status=int(exc.code),
            http_detail=detail[:240],
        )
    except urllib.error.URLError as exc:
        return _result(
            reachable=False,
            model_available=False,
            auth_ok=False,
            error_code="unreachable",
            error=str(getattr(exc, "reason", exc) or exc),
        )
    except TimeoutError:
        return _result(
            reachable=False,
            model_available=False,
            auth_ok=False,
            error_code="timeout",
            error=f"timed out after {timeout_sec:.0f}s",
        )
    except json.JSONDecodeError as exc:
        return _result(
            reachable=False,
            model_available=False,
            auth_ok=False,
            error_code="invalid_json",
            error=f"invalid JSON from /models: {exc}",
        )

    model_ids = {
        str(item.get("id", "") or "").strip()
        for item in (payload.get("data") or [])
        if isinstance(item, dict)
    }
    available_models = sorted(model_ids)
    model_available = model in model_ids
    sample_models = ", ".join(available_models[:8])
    if not model_available:
        suffix = f" Available: {sample_models}" if sample_models else ""
        if len(available_models) > 8:
            suffix += f" (+{len(available_models) - 8} more)"
        return _result(
            reachable=True,
            model_available=False,
            auth_ok=True,
            error_code="model_not_found",
            error=f"model {model!r} not listed by server.{suffix}",
            available_models=available_models,
        )
    return _result(
        reachable=True,
        model_available=True,
        auth_ok=True,
        error_code="",
        error="",
        available_models=available_models,
    )


def build_remote_vlm_probe_config(remote_vlm: Mapping[str, Any]) -> dict[str, Any]:
    return {"understanding": {"remote_vlm": dict(remote_vlm or {})}}


def probe_remote_vlm_draft(remote_vlm: Mapping[str, Any], *, timeout_sec: float = 8.0) -> dict[str, Any]:
    return probe_remote_vlm(build_remote_vlm_probe_config(remote_vlm), timeout_sec=timeout_sec)


def load_profile_manifest(profile_id: str, model_dir: str | None = None) -> dict[str, Any]:
    profile_text = str(profile_id or "").strip()
    if not profile_text:
        raise UnderstandingManifestError("profile_id is required")

    installed_path = get_profile_manifest_path(profile_text, model_dir=model_dir)
    if os.path.isfile(installed_path):
        manifest = _read_json_file(installed_path)
        return validate_profile_manifest(manifest, profile_dir=os.path.dirname(installed_path))

    for manifest_path in _iter_builtin_profile_manifest_paths():
        manifest = _read_json_file(manifest_path)
        if str(manifest.get("id", "") or "").strip() == profile_text:
            return validate_profile_manifest(manifest, profile_dir=os.path.dirname(manifest_path))

    raise UnderstandingManifestError(f"profile manifest not found: {profile_text}")


def ensure_understanding_profiles_installed(model_dir: str | None = None) -> list[str]:
    import shutil

    installed: list[str] = []
    resolved_model_dir = _resolve_model_dir(model_dir)
    profiles_root = get_understanding_profiles_root(resolved_model_dir)
    os.makedirs(profiles_root, exist_ok=True)

    for manifest_path in _iter_builtin_profile_manifest_paths():
        manifest = validate_profile_manifest(
            _read_json_file(manifest_path),
            profile_dir=os.path.dirname(manifest_path),
        )
        profile_id = manifest["id"]
        target_dir = get_profile_dir(profile_id, model_dir=resolved_model_dir)
        target_manifest = get_profile_manifest_path(profile_id, model_dir=resolved_model_dir)
        if os.path.isfile(target_manifest):
            try:
                shutil.copy2(manifest_path, target_manifest)
            except OSError as exc:
                logger.warning("Failed to refresh builtin profile manifest %s: %s", target_manifest, exc)
            continue
        source_dir = os.path.dirname(manifest_path)
        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)
        installed.append(profile_id)
    return installed


def ensure_understanding_components_installed(model_dir: str | None = None) -> list[str]:
    import shutil

    installed: list[str] = []
    resolved_model_dir = _resolve_model_dir(model_dir)
    components_root = get_understanding_components_root(resolved_model_dir)
    os.makedirs(components_root, exist_ok=True)

    for manifest_path in _iter_builtin_component_manifest_paths():
        manifest = validate_component_manifest(
            _read_json_file(manifest_path),
            component_dir=os.path.dirname(manifest_path),
        )
        component_id = manifest["id"]
        target_manifest = get_component_manifest_path(component_id, model_dir=resolved_model_dir)
        if os.path.isfile(target_manifest):
            continue
        source_dir = os.path.dirname(manifest_path)
        target_dir = get_component_dir(component_id, model_dir=resolved_model_dir)
        os.makedirs(os.path.dirname(target_dir), exist_ok=True)
        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)
        installed.append(component_id)
    return installed


def get_required_component_ids(profile_manifest: Mapping[str, Any]) -> list[str]:
    requires = _require_mapping(profile_manifest.get("requires"), "requires")
    components = requires.get("components")
    if not isinstance(components, list) or not components:
        raise UnderstandingManifestError("requires.components must be a non-empty list")
    return [_require_text(item, "requires.components") for item in components]


def get_optional_component_ids(profile_manifest: Mapping[str, Any]) -> list[str]:
    requires = _require_mapping(profile_manifest.get("requires"), "requires")
    components = requires.get("optional_components", [])
    if components is None:
        return []
    if not isinstance(components, list):
        raise UnderstandingManifestError("requires.optional_components must be a list")
    return [_require_text(item, "requires.optional_components") for item in components]


def is_component_installed(component_id: str, model_dir: str | None = None) -> bool:
    component_text = str(component_id or "").strip()
    if not component_text:
        return False
    for item in scan_understanding_components(model_dir=model_dir):
        if str(item.get("id", "") or "").strip() == component_text:
            return bool(item.get("installed"))
    return False


def _missing_components_for_ids(
    component_ids: list[str],
    *,
    config: Mapping[str, Any] | None = None,
    model_dir: str | None = None,
    remote_probe: Mapping[str, Any] | None = None,
    check_remote: bool = True,
    scanned_components: list[dict[str, Any]] | None = None,
) -> list[str]:
    components = (
        scanned_components
        if scanned_components is not None
        else scan_understanding_components(model_dir=model_dir)
    )
    installed = {
        str(item.get("id", "") or "").strip()
        for item in components
        if item.get("installed")
    }
    missing = [component_id for component_id in component_ids if component_id not in installed]

    if check_remote:
        probe = remote_probe if remote_probe is not None else probe_remote_vlm(config, timeout_sec=3.0)
        remote_ok = bool(probe.get("reachable")) and bool(probe.get("model_available"))
        if not remote_ok:
            for component_id in component_ids:
                if _component_delivery(component_id, model_dir=model_dir) == "remote" and component_id not in missing:
                    missing.append(component_id)
    return missing


def _component_delivery(component_id: str, model_dir: str | None = None) -> str:
    manifest_path = get_component_manifest_path(component_id, model_dir=model_dir)
    if not os.path.isfile(manifest_path):
        manifest_path = get_builtin_component_manifest_path(component_id) or ""
    if not manifest_path or not os.path.isfile(manifest_path):
        return "local"
    try:
        manifest = validate_component_manifest(_read_json_file(manifest_path))
    except Exception:
        return "local"
    return str(manifest.get("delivery", "local") or "local").strip().lower()


def get_missing_components_for_profile(
    profile_id: str,
    *,
    config: Mapping[str, Any] | None = None,
    model_dir: str | None = None,
    remote_probe: Mapping[str, Any] | None = None,
    check_remote: bool = True,
    scanned_components: list[dict[str, Any]] | None = None,
) -> list[str]:
    profile_manifest = load_profile_manifest(profile_id, model_dir=model_dir)
    required_ids = get_required_component_ids(profile_manifest)
    return _missing_components_for_ids(
        required_ids,
        config=config,
        model_dir=model_dir,
        remote_probe=remote_probe,
        check_remote=check_remote,
        scanned_components=scanned_components,
    )


def get_missing_optional_components_for_profile(
    profile_id: str,
    *,
    config: Mapping[str, Any] | None = None,
    model_dir: str | None = None,
    remote_probe: Mapping[str, Any] | None = None,
    check_remote: bool = False,
    scanned_components: list[dict[str, Any]] | None = None,
) -> list[str]:
    profile_manifest = load_profile_manifest(profile_id, model_dir=model_dir)
    optional_ids = get_optional_component_ids(profile_manifest)
    if not optional_ids:
        return []
    return _missing_components_for_ids(
        optional_ids,
        config=config,
        model_dir=model_dir,
        remote_probe=remote_probe,
        check_remote=check_remote,
        scanned_components=scanned_components,
    )


def get_understanding_resource_status(
    config: Mapping[str, Any] | None = None,
    model_dir: str | None = None,
    *,
    probe_remote: bool = True,
    remote_probe_timeout_sec: float = 3.0,
    install_bootstrap: bool = True,
) -> dict[str, Any]:
    normalized_config = normalize_understanding_config(config)
    active_profile_id = get_active_understanding_profile_id(normalized_config)
    resolved_model_dir = str(model_dir or get_configured_model_dir() or "").strip()

    if probe_remote:
        remote_vlm = probe_remote_vlm(normalized_config, timeout_sec=remote_probe_timeout_sec)
    else:
        remote_vlm = {"skipped": True}

    missing_components: list[str] = []
    optional_missing_components: list[str] = []
    profile_error = ""
    try:
        if install_bootstrap:
            ensure_understanding_profiles_installed(model_dir=resolved_model_dir or None)
            ensure_understanding_components_installed(model_dir=resolved_model_dir or None)
        # Scan once; missing-required / missing-optional / status payload all reuse it.
        components = scan_understanding_components(model_dir=resolved_model_dir or None)
        missing_components = get_missing_components_for_profile(
            active_profile_id,
            config=normalized_config,
            model_dir=resolved_model_dir or None,
            remote_probe=remote_vlm if probe_remote else None,
            check_remote=probe_remote,
            scanned_components=components,
        )
        optional_missing_components = get_missing_optional_components_for_profile(
            active_profile_id,
            config=normalized_config,
            model_dir=resolved_model_dir or None,
            remote_probe=remote_vlm if probe_remote else None,
            check_remote=False,
            scanned_components=components,
        )
    except Exception as exc:
        profile_error = str(exc)
        missing_components = []
        optional_missing_components = []
        components = scan_understanding_components(model_dir=resolved_model_dir or None)

    installed_components = [item["id"] for item in components if item.get("installed")]
    understanding_ready = not profile_error and not missing_components
    return {
        "understanding_ready": understanding_ready,
        "active_understanding_profile": active_profile_id,
        "understanding_root": get_understanding_root(resolved_model_dir) if resolved_model_dir else "",
        "installed_components": installed_components,
        "missing_components": missing_components,
        "optional_missing_components": optional_missing_components,
        "components": components,
        "profile_error": profile_error,
        "remote_vlm": remote_vlm,
    }


def get_active_understanding_profile(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    normalized_config = normalize_understanding_config(config)
    active_profile_id = get_active_understanding_profile_id(normalized_config)
    profile_manifest = load_profile_manifest(active_profile_id)
    config_profiles = {
        str(item.get("id", "") or "").strip(): item for item in get_understanding_profiles(normalized_config)
    }
    config_entry = dict(config_profiles.get(active_profile_id) or {})
    return {
        "id": active_profile_id,
        "display_name": str(config_entry.get("display_name", "") or profile_manifest.get("display_name", active_profile_id)),
        "profile_dir": str(config_entry.get("profile_dir", "") or active_profile_id),
        "enabled": bool(config_entry.get("enabled", True)),
        "manifest": profile_manifest,
    }
