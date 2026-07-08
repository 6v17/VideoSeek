"""Search preset paths, JSON persistence, and reference file resolution."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from src.app.config import get_configured_data_root, load_config
from src.app.logging_utils import get_logger
from src.storage.config_store import get_active_model_profile

from src.services.search_preset_constants import PRESET_SCHEMA_VERSION

logger = get_logger("search_preset_storage")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _suppressed_builtin_ids(document: dict) -> set[str]:
    raw = (document or {}).get("suppressed_builtin_ids") or []
    if not isinstance(raw, list):
        return set()
    return {str(item or "").strip() for item in raw if str(item or "").strip()}


def get_active_profile_id(config=None) -> str:
    profile = get_active_model_profile(config=config or load_config())
    profile_id = str(profile.get("id", "") or "").strip()
    if not profile_id:
        raise RuntimeError("Missing active model profile")
    return profile_id


def get_search_presets_base_dir(config=None) -> str:
    cfg = config or load_config()
    return os.path.join(get_configured_data_root(cfg), "data", "search_presets")


def get_search_preset_root(config=None) -> str:
    """Shared preset storage root (presets.json + refs/)."""
    return get_search_presets_base_dir(config)


def get_presets_file(config=None) -> str:
    return os.path.join(get_search_preset_root(config), "presets.json")


def get_preset_refs_dir(config=None) -> str:
    return os.path.join(get_search_preset_root(config), "refs")


def get_preset_query_cache_root(config=None) -> str:
    return os.path.join(get_search_presets_base_dir(config), "query_cache")


def get_preset_query_cache_dir(config=None) -> str:
    profile_id = get_active_profile_id(config)
    return os.path.join(get_preset_query_cache_root(config), profile_id)


def query_cache_path(preset_id: str, config=None, *, profile_id: str | None = None) -> str:
    preset_id = str(preset_id or "").strip()
    cache_dir = (
        os.path.join(get_preset_query_cache_root(config), profile_id)
        if profile_id
        else get_preset_query_cache_dir(config)
    )
    return os.path.join(cache_dir, f"{preset_id}.npy")


def _resolve_ref_rel_path(ref_file: str, config=None) -> str:
    ref_file = str(ref_file or "").strip()
    if not ref_file:
        return ""
    if os.path.isabs(ref_file):
        return ref_file
    return os.path.join(get_search_preset_root(config), ref_file.replace("/", os.sep))


def resolve_preset_ref_paths(preset: dict, config=None) -> list[str]:
    paths = []
    for ref_file in list((preset or {}).get("ref_files") or []):
        resolved = _resolve_ref_rel_path(ref_file, config=config)
        if resolved and os.path.isfile(resolved):
            paths.append(resolved)
    if paths:
        return paths
    legacy = _resolve_ref_rel_path((preset or {}).get("ref_file", ""), config=config)
    if legacy and os.path.isfile(legacy):
        return [legacy]
    return []


def get_preset_ref_path(preset: dict, config=None) -> str:
    paths = resolve_preset_ref_paths(preset, config=config)
    return paths[0] if paths else ""


def _atomic_write_json(path: str, payload: dict) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _empty_document() -> dict:
    return {
        "version": PRESET_SCHEMA_VERSION,
        "presets": [],
        "suppressed_builtin_ids": [],
    }


def _read_presets_payload(path: str) -> dict:
    if not os.path.isfile(path):
        return _empty_document()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        logger.warning("Failed to read search presets file %s: %s", path, exc)
        return _empty_document()
    if not isinstance(payload, dict):
        return _empty_document()
    presets = payload.get("presets")
    if not isinstance(presets, list):
        presets = []
    suppressed = payload.get("suppressed_builtin_ids")
    if not isinstance(suppressed, list):
        suppressed = []
    return {
        "version": int(payload.get("version", PRESET_SCHEMA_VERSION) or PRESET_SCHEMA_VERSION),
        "presets": [item for item in presets if isinstance(item, dict)],
        "suppressed_builtin_ids": [
            str(item or "").strip() for item in suppressed if str(item or "").strip()
        ],
    }


def load_presets_document(config=None) -> dict:
    cfg = config or load_config()
    return _read_presets_payload(get_presets_file(cfg))


def save_presets_document(document: dict, config=None) -> None:
    payload = dict(document or {})
    payload["version"] = PRESET_SCHEMA_VERSION
    presets = payload.get("presets")
    if not isinstance(presets, list):
        presets = []
    payload["presets"] = presets
    payload["suppressed_builtin_ids"] = sorted(_suppressed_builtin_ids(payload))
    payload.pop("model_profile_id", None)
    _atomic_write_json(get_presets_file(config), payload)
