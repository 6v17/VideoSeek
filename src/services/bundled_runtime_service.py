"""First-run import from ``{install_dir}/runtime`` (full edition seed zips + ffmpeg)."""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Mapping

from src.infra.paths import get_bundled_runtime_dir

BUNDLED_RUNTIME_MANIFEST_NAME = "manifest.json"


def load_bundled_runtime_manifest(*, runtime_dir: str | None = None) -> dict[str, Any] | None:
    root = str(runtime_dir or get_bundled_runtime_dir()).strip()
    if not root:
        return None
    manifest_path = os.path.join(root, BUNDLED_RUNTIME_MANIFEST_NAME)
    if not os.path.isfile(manifest_path):
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def bundled_runtime_available(*, runtime_dir: str | None = None) -> bool:
    manifest = load_bundled_runtime_manifest(runtime_dir=runtime_dir)
    if not manifest:
        return False
    root = str(runtime_dir or get_bundled_runtime_dir()).strip()
    files = _manifest_file_names(manifest)
    if not files:
        return False
    return all(os.path.isfile(os.path.join(root, name)) for name in files)


def resolve_bundled_runtime_paths(*, runtime_dir: str | None = None) -> list[str]:
    manifest = load_bundled_runtime_manifest(runtime_dir=runtime_dir)
    if not manifest:
        return []
    root = str(runtime_dir or get_bundled_runtime_dir()).strip()
    paths: list[str] = []
    for name in _manifest_file_names(manifest):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            paths.append(os.path.normpath(path))
    return paths


def bootstrap_bundled_runtime(
    *,
    progress_callback: Callable[[int, str], None] | None = None,
    runtime_dir: str | None = None,
) -> dict[str, Any]:
    from src.app.config import load_config, save_config
    from src.services.runtime_resource_service import (
        ensure_runtime_resource_dirs,
        get_runtime_resource_status,
        import_runtime_resources,
    )
    from src.utils import get_app_data_dir

    def _progress(value: int, text: str) -> None:
        if progress_callback:
            progress_callback(int(value), str(text or ""))

    status = get_runtime_resource_status()
    if status.get("resources_ready"):
        return {"ok": True, "skipped": "already_ready", "status": status}

    manifest = load_bundled_runtime_manifest(runtime_dir=runtime_dir)
    if not manifest:
        return {"ok": False, "skipped": "no_manifest", "status": status}

    root = str(runtime_dir or get_bundled_runtime_dir()).strip()
    expected = _manifest_file_names(manifest)
    paths = resolve_bundled_runtime_paths(runtime_dir=root)
    missing = [name for name in expected if not os.path.isfile(os.path.join(root, name))]
    if missing:
        return {
            "ok": False,
            "error": "missing bundled files: " + ", ".join(missing),
            "status": status,
        }
    if not paths:
        return {"ok": False, "error": "no bundled runtime files found", "status": status}

    config = load_config()
    if not str(config.get("model_dir") or "").strip():
        config["model_dir"] = os.path.join(get_app_data_dir(), "models")
        save_config(config)
    ensure_runtime_resource_dirs()

    _progress(5, "Importing bundled runtime resources")
    try:
        payload = import_runtime_resources(paths)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "status": get_runtime_resource_status()}

    profile_id = str(manifest.get("prefer_active_profile_id") or "").strip()
    if profile_id:
        _apply_prefer_active_profile(profile_id)

    _progress(100, "Bundled runtime import finished")
    final = get_runtime_resource_status()
    return {
        "ok": bool(final.get("resources_ready")),
        "payload": payload,
        "status": final,
        "edition": str(manifest.get("edition") or "full"),
    }


def _manifest_file_names(manifest: Mapping[str, Any]) -> list[str]:
    raw = manifest.get("files")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        text = str(item or "").strip().replace("\\", "/")
        if not text or "/" in text or text.startswith(".."):
            continue
        names.append(os.path.basename(text))
    return names


def _apply_prefer_active_profile(profile_id: str) -> bool:
    from src.app.config import load_config, save_config

    config = load_config()
    models = config.get("models") if isinstance(config.get("models"), dict) else {}
    profiles = models.get("profiles") if isinstance(models.get("profiles"), list) else []
    if not any(str(item.get("id") or "") == profile_id for item in profiles if isinstance(item, dict)):
        return False
    models = dict(models)
    if str(models.get("active_profile") or "") == profile_id:
        return False
    models["active_profile"] = profile_id
    config["models"] = models
    save_config(config)
    return True
