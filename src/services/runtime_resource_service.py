import os

from src.app.app_meta import get_app_meta
from src.services.model_service import REQUIRED_MODEL_FILES
from src.utils import (
    get_app_data_dir,
    get_configured_ffmpeg_target_path,
    get_configured_model_dir,
    get_missing_model_files,
    has_ffmpeg,
)


def get_runtime_resource_status():
    missing_model_files, _ = get_missing_model_files(REQUIRED_MODEL_FILES)
    ffmpeg_ready = has_ffmpeg()
    model_ready = not missing_model_files
    model_dir = get_configured_model_dir()
    ffmpeg_target_path = get_configured_ffmpeg_target_path()

    display_files = list(missing_model_files)
    if not ffmpeg_ready:
        display_files.append("ffmpeg.exe")

    return {
        "root_dir": get_app_data_dir(),
        "model_dir": model_dir,
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
    model_dir = os.path.normpath(status["model_dir"])
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
    os.makedirs(status["model_dir"], exist_ok=True)
    os.makedirs(os.path.dirname(status["ffmpeg_target_path"]), exist_ok=True)
    return get_runtime_resource_open_paths(status)
