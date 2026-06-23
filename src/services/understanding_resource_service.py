from __future__ import annotations

import copy
import json
import os
from typing import Any, Mapping

from src.app.config import load_config, save_config
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

DEFAULT_UNDERSTANDING_CONFIG = {
    "active_profile": "vision_baseline_v1",
    "profiles": list(DEFAULT_UNDERSTANDING_PROFILES),
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
    if not isinstance(required_files, list) or not required_files:
        raise UnderstandingManifestError("required_files must be a non-empty list")
    normalized_required = [_require_text(name, f"required_files[{index}]") for index, name in enumerate(required_files)]

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

    understanding = {
        "active_profile": active_profile,
        "profiles": normalized_profiles,
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
            continue
        source_dir = os.path.dirname(manifest_path)
        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)
        installed.append(profile_id)
    return installed


def get_required_component_ids(profile_manifest: Mapping[str, Any]) -> list[str]:
    requires = _require_mapping(profile_manifest.get("requires"), "requires")
    components = requires.get("components")
    if not isinstance(components, list):
        raise UnderstandingManifestError("requires.components must be a list")
    return [_require_text(item, "requires.components") for item in components]


def get_missing_components_for_profile(
    profile_id: str,
    *,
    config: Mapping[str, Any] | None = None,
    model_dir: str | None = None,
) -> list[str]:
    profile_manifest = load_profile_manifest(profile_id, model_dir=model_dir)
    required_ids = get_required_component_ids(profile_manifest)
    installed = {
        str(item.get("id", "") or "").strip()
        for item in scan_understanding_components(model_dir=model_dir)
        if item.get("installed")
    }
    return [component_id for component_id in required_ids if component_id not in installed]


def get_understanding_resource_status(
    config: Mapping[str, Any] | None = None,
    model_dir: str | None = None,
) -> dict[str, Any]:
    normalized_config = normalize_understanding_config(config)
    active_profile_id = get_active_understanding_profile_id(normalized_config)
    resolved_model_dir = str(model_dir or get_configured_model_dir() or "").strip()
    components = scan_understanding_components(model_dir=resolved_model_dir or None)
    installed_components = [item["id"] for item in components if item.get("installed")]

    missing_components: list[str] = []
    profile_error = ""
    try:
        ensure_understanding_profiles_installed(model_dir=resolved_model_dir or None)
        missing_components = get_missing_components_for_profile(
            active_profile_id,
            config=normalized_config,
            model_dir=resolved_model_dir or None,
        )
    except Exception as exc:
        profile_error = str(exc)
        missing_components = []

    understanding_ready = not profile_error and not missing_components
    return {
        "understanding_ready": understanding_ready,
        "active_understanding_profile": active_profile_id,
        "understanding_root": get_understanding_root(resolved_model_dir) if resolved_model_dir else "",
        "installed_components": installed_components,
        "missing_components": missing_components,
        "components": components,
        "profile_error": profile_error,
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
