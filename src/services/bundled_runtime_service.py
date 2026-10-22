"""First-run import from ``{install_dir}/runtime`` (full edition seed zips + ffmpeg)."""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Mapping

from src.infra.paths import get_bundled_runtime_dir

BUNDLED_RUNTIME_MANIFEST_NAME = "manifest.json"
BUNDLED_CHINESE_CLIP_VARIANT = "vit-base-patch16"


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


def is_chinese_clip_bundled_variant_installed(*, model_root: str | None = None) -> bool:
    from src.services.model_package_service import PROVIDER_REQUIRED_MODEL_FILES
    from src.services.runtime_resource_service import get_runtime_resource_status

    status = get_runtime_resource_status()
    root = str(model_root or status.get("model_root_dir") or status.get("model_dir") or "").strip()
    if not root:
        from src.utils import get_app_data_dir

        root = os.path.join(get_app_data_dir(), "models")
    variant_dir = os.path.join(root, "chinese-clip", BUNDLED_CHINESE_CLIP_VARIANT)
    manifest_path = os.path.join(variant_dir, "model_manifest.json")
    if not os.path.isfile(manifest_path):
        return False
    required = list(PROVIDER_REQUIRED_MODEL_FILES.get("chinese_clip_onnx") or [])
    return all(os.path.isfile(os.path.join(variant_dir, name)) for name in required)


def is_bundled_rapidocr_installed() -> bool:
    from src.core.subtitle_ocr.rapidocr_engine import resolve_rapidocr_model_dir

    return bool(resolve_rapidocr_model_dir())


def plan_bundled_import(*, runtime_dir: str | None = None) -> dict[str, Any]:
    """Decide which seed files to import. Existing users get supplements only; active profile stays."""
    from src.services.runtime_resource_service import get_runtime_resource_status
    from src.utils import has_ffmpeg

    empty = {
        "paths": [],
        "switch_active_profile": False,
        "prefer_active_profile_id": "",
        "supplemental": False,
        "first_install": False,
    }
    if not bundled_runtime_available(runtime_dir=runtime_dir):
        return dict(empty)

    manifest = load_bundled_runtime_manifest(runtime_dir=runtime_dir)
    if not manifest:
        return dict(empty)

    status = get_runtime_resource_status()
    first_install = not bool(status.get("resources_ready"))
    all_paths = resolve_bundled_runtime_paths(runtime_dir=runtime_dir)
    selected: list[str] = []

    if first_install:
        selected = list(all_paths)
    else:
        for path in all_paths:
            name = os.path.basename(path).lower()
            if name == "ffmpeg.exe":
                if not has_ffmpeg():
                    selected.append(path)
            elif "chinese-clip" in name:
                if not is_chinese_clip_bundled_variant_installed():
                    selected.append(path)
            elif "rapidocr" in name:
                if not is_bundled_rapidocr_installed():
                    selected.append(path)

    prefer_id = str(manifest.get("prefer_active_profile_id") or "").strip()
    return {
        "paths": selected,
        "switch_active_profile": first_install and bool(prefer_id),
        "prefer_active_profile_id": prefer_id if first_install else "",
        "supplemental": not first_install and bool(selected),
        "first_install": first_install,
    }


def has_pending_bundled_import(*, runtime_dir: str | None = None) -> bool:
    return bool(plan_bundled_import(runtime_dir=runtime_dir).get("paths"))


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
    plan = plan_bundled_import(runtime_dir=runtime_dir)
    paths = list(plan.get("paths") or [])
    if not paths:
        return {
            "ok": True,
            "skipped": "nothing_to_import",
            "status": status,
            "supplemental": bool(plan.get("supplemental")),
        }

    manifest = load_bundled_runtime_manifest(runtime_dir=runtime_dir)
    if not manifest:
        return {"ok": False, "skipped": "no_manifest", "status": status}

    config = load_config()
    if not str(config.get("model_dir") or "").strip():
        config["model_dir"] = os.path.join(get_app_data_dir(), "models")
        save_config(config)
    ensure_runtime_resource_dirs()

    from src.services.bundled_runtime_errors import check_disk_space_for_import

    model_root = str(config.get("model_dir") or os.path.join(get_app_data_dir(), "models"))
    space_error = check_disk_space_for_import(paths, target_dir=model_root)
    if space_error:
        return {
            "ok": False,
            "error": space_error,
            "error_code": "disk_full",
            "status": get_runtime_resource_status(),
            "supplemental": bool(plan.get("supplemental")),
        }

    _progress(2, "Importing bundled runtime resources")
    try:
        payload = import_runtime_resources(paths, progress_callback=_progress)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "status": get_runtime_resource_status(),
            "supplemental": bool(plan.get("supplemental")),
        }

    package_errors = []
    packages = payload.get("packages") if isinstance(payload.get("packages"), dict) else {}
    if isinstance(packages, dict):
        package_errors = [str(item) for item in (packages.get("errors") or []) if str(item).strip()]
    if package_errors:
        return {
            "ok": False,
            "error": "; ".join(package_errors[:4]),
            "status": get_runtime_resource_status(),
            "supplemental": bool(plan.get("supplemental")),
            "partial": True,
        }

    if plan.get("switch_active_profile") and str(plan.get("prefer_active_profile_id") or "").strip():
        _apply_prefer_active_profile(str(plan["prefer_active_profile_id"]))

    _progress(100, "Bundled runtime import finished")
    final = get_runtime_resource_status()
    ok = bool(final.get("resources_ready")) or bool(plan.get("supplemental"))
    return {
        "ok": ok,
        "payload": payload,
        "status": final,
        "edition": str(manifest.get("edition") or "full"),
        "supplemental": bool(plan.get("supplemental")),
        "imported_paths": [os.path.basename(path) for path in paths],
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
