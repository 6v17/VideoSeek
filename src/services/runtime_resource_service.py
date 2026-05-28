import os

from src.app.app_meta import get_app_meta
from src.app.config import load_config
from src.services.model_service import get_required_model_files
from src.storage.config_store import get_active_model_profile, get_active_model_resource_dir, resolve_provider_dir
from src.utils import (
    get_app_data_dir,
    get_configured_ffmpeg_target_path,
    get_missing_model_files,
    has_ffmpeg,
)


def _resolve_runtime_model_dir(config):
    try:
        model_dir = get_active_model_resource_dir(config=config)
        if model_dir:
            return model_dir
    except Exception:
        pass
    return str(config.get("model_dir", "") or "").strip()


def _resolve_runtime_model_root_dir(config):
    model_root_dir = str(config.get("model_dir", "") or "").strip()
    if not model_root_dir:
        model_root_dir = _resolve_runtime_model_dir(config)
    model_root_dir = str(model_root_dir or "").strip()
    if not model_root_dir:
        return ""
    model_root_dir = os.path.normpath(os.path.abspath(os.fspath(model_root_dir)))
    try:
        profile = get_active_model_profile(config=config)
        provider = str(profile.get("provider", "") or "").strip()
        runtime = dict(profile.get("runtime") or {})
        variant = str(runtime.get("model_variant", "") or profile.get("model_variant", "") or "").strip()
        if provider and variant:
            provider_dir = resolve_provider_dir(provider)
            expected_tail = os.path.normcase(os.path.normpath(os.path.join(provider_dir, variant)))
            if os.path.normcase(model_root_dir).endswith(expected_tail):
                candidate = os.path.dirname(os.path.dirname(model_root_dir))
                if candidate:
                    model_root_dir = candidate
    except Exception:
        pass
    # Fallback heuristic: if path itself looks like "<root>/<provider>/<variant>", trim to "<root>".
    # This protects against stale configs that accidentally persist a profile leaf as model_dir.
    provider_leaf = os.path.basename(os.path.dirname(model_root_dir)).strip().lower()
    if provider_leaf in {"openai-clip", "siglip2", "chinese-clip", "chinese-clip-onnx", "clip-onnx", "siglip2-onnx"}:
        candidate = os.path.dirname(os.path.dirname(model_root_dir))
        if candidate:
            model_root_dir = candidate
    return model_root_dir


def get_runtime_resource_status():
    config = load_config()
    missing_model_files, _ = get_missing_model_files(get_required_model_files(config=config))
    ffmpeg_ready = has_ffmpeg()
    model_ready = not missing_model_files
    model_dir = _resolve_runtime_model_dir(config)
    model_root_dir = _resolve_runtime_model_root_dir(config)
    ffmpeg_target_path = get_configured_ffmpeg_target_path()

    display_files = list(missing_model_files)
    if not ffmpeg_ready:
        display_files.append("ffmpeg.exe")

    return {
        "root_dir": get_app_data_dir(),
        "model_dir": model_dir,
        "model_root_dir": model_root_dir,
        "ffmpeg_target_path": ffmpeg_target_path,
        "missing_model_files": missing_model_files,
        "display_files": display_files,
        "model_ready": model_ready,
        "ffmpeg_ready": ffmpeg_ready,
        "resources_ready": model_ready and ffmpeg_ready,
        "download_enabled": bool(get_app_meta().get("model_manifest_url", "").strip()),
    }


def get_runtime_resource_location_text(status=None, include_ffmpeg=True):
    status = status or get_runtime_resource_status()
    locations = [f"Models: {status['model_dir']}"]
    if include_ffmpeg:
        locations.append(f"FFmpeg: {status['ffmpeg_target_path']}")
    return "\n".join(locations)


def get_runtime_resource_open_paths(status=None):
    status = status or get_runtime_resource_status()
    model_dir = os.path.normpath(str(status.get("model_root_dir") or status["model_dir"]))
    ffmpeg_dir = os.path.normpath(os.path.dirname(status["ffmpeg_target_path"]))
    paths = []

    if model_dir:
        paths.append(model_dir)
    if ffmpeg_dir and os.path.normcase(ffmpeg_dir) != os.path.normcase(model_dir):
        paths.append(ffmpeg_dir)

    deduped = []
    seen = set()
    for path in paths:
        normalized = os.path.normcase(path)
        if normalized in seen:
            continue
        deduped.append(path)
        seen.add(normalized)
    return deduped


def ensure_runtime_resource_dirs(status=None):
    status = status or get_runtime_resource_status()
    os.makedirs(status["root_dir"], exist_ok=True)
    model_root_dir = str(status.get("model_root_dir", "") or "").strip()
    if not model_root_dir:
        model_root_dir = str(status.get("model_dir", "") or "").strip()
    if model_root_dir:
        os.makedirs(model_root_dir, exist_ok=True)
    os.makedirs(os.path.dirname(status["ffmpeg_target_path"]), exist_ok=True)
    return get_runtime_resource_open_paths(status)
