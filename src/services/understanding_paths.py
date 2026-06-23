from __future__ import annotations

import os
import re

from src.app.config import get_data_storage_paths
from src.utils import get_configured_model_dir, get_resource_path

UNDERSTANDING_DIR_NAME = "understanding"
COMPONENTS_DIR_NAME = "components"
PROFILES_DIR_NAME = "profiles"
EVIDENCE_DIR_NAME = "evidence"
EVIDENCE_VIDEOS_DIR_NAME = "videos"
BUILTIN_PROFILES_RELPATH = os.path.join("resources", "understanding_profiles")
COMPONENT_ID_PATTERN = re.compile(
    r"^(?P<modality>[a-z][a-z0-9_]*)/(?P<task>[a-z][a-z0-9_]*)/(?P<model_id>[a-z0-9][a-z0-9_-]*)$"
)


def _normalize_video_id(video_id: str) -> str:
    text = str(video_id or "").strip()
    if not text:
        raise ValueError("video_id is required")
    if os.path.basename(text) != text or ".." in text.split(os.sep):
        raise ValueError(f"invalid video_id: {video_id!r}")
    return text


def _resolve_model_dir(model_dir: str | None) -> str:
    resolved = str(model_dir or get_configured_model_dir() or "").strip()
    if not resolved:
        raise ValueError("model_dir is not configured")
    return os.path.normpath(resolved)


def parse_component_id(component_id: str) -> tuple[str, str, str]:
    text = str(component_id or "").strip()
    match = COMPONENT_ID_PATTERN.fullmatch(text)
    if not match:
        raise ValueError(
            f"component_id must match '<modality>/<task>/<model_id>', got {component_id!r}"
        )
    return match.group("modality"), match.group("task"), match.group("model_id")


def build_component_id(modality: str, task: str, model_id: str) -> str:
    modality_text = str(modality or "").strip()
    task_text = str(task or "").strip()
    model_id_text = str(model_id or "").strip()
    if not modality_text or not task_text or not model_id_text:
        raise ValueError("modality, task, and model_id are required")
    return f"{modality_text}/{task_text}/{model_id_text}"


def build_component_install_relpath(modality: str, task: str, model_id: str) -> str:
    return os.path.join(
        COMPONENTS_DIR_NAME,
        build_component_id(modality, task, model_id).replace("/", os.sep),
    )


def get_understanding_root(model_dir: str | None = None) -> str:
    return os.path.join(_resolve_model_dir(model_dir), UNDERSTANDING_DIR_NAME)


def get_understanding_components_root(model_dir: str | None = None) -> str:
    return os.path.join(get_understanding_root(model_dir), COMPONENTS_DIR_NAME)


def get_understanding_profiles_root(model_dir: str | None = None) -> str:
    return os.path.join(get_understanding_root(model_dir), PROFILES_DIR_NAME)


def get_component_dir(component_id: str, model_dir: str | None = None) -> str:
    modality, task, model_id = parse_component_id(component_id)
    return os.path.join(
        get_understanding_components_root(model_dir),
        modality,
        task,
        model_id,
    )


def get_component_manifest_path(component_id: str, model_dir: str | None = None) -> str:
    return os.path.join(get_component_dir(component_id, model_dir=model_dir), "understanding_manifest.json")


def get_profile_dir(profile_id: str, model_dir: str | None = None) -> str:
    profile_text = str(profile_id or "").strip()
    if not profile_text:
        raise ValueError("profile_id is required")
    if os.path.basename(profile_text) != profile_text:
        raise ValueError(f"invalid profile_id: {profile_id!r}")
    return os.path.join(get_understanding_profiles_root(model_dir), profile_text)


def get_profile_manifest_path(profile_id: str, model_dir: str | None = None) -> str:
    return os.path.join(get_profile_dir(profile_id, model_dir=model_dir), "profile_manifest.json")


def get_builtin_profiles_dir() -> str:
    return os.path.normpath(get_resource_path(BUILTIN_PROFILES_RELPATH))


def get_evidence_root(config=None) -> str:
    data_paths = get_data_storage_paths(config=config)
    data_dir = str(data_paths.get("data_dir", "") or "").strip()
    if not data_dir:
        raise ValueError("data_dir is not configured")
    return os.path.join(data_dir, EVIDENCE_DIR_NAME)


def get_evidence_videos_dir(config=None) -> str:
    return os.path.join(get_evidence_root(config=config), EVIDENCE_VIDEOS_DIR_NAME)


def get_evidence_path(video_id: str, config=None) -> str:
    normalized_id = _normalize_video_id(video_id)
    return os.path.join(get_evidence_videos_dir(config=config), f"{normalized_id}.json")
