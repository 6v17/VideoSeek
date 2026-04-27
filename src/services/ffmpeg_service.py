import json
import os
import urllib.request

from src.app.app_meta import get_app_meta
from src.app.config import load_config, save_config
from src.services.download_utils import download_file
from src.utils import ensure_folder_exists, get_configured_ffmpeg_target_path


def fetch_remote_ffmpeg_manifest():
    app_meta = get_app_meta()
    manifest_url = app_meta.get("model_manifest_url", "").strip()
    timeout = app_meta.get("remote_timeout", 4)
    if not manifest_url:
        return None

    request = urllib.request.Request(
        manifest_url,
        headers={"User-Agent": "VideoSeek/ffmpeg-manifest"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    return _normalize_ffmpeg_entry(data, manifest_url)


def download_ffmpeg(progress_callback=None):
    ffmpeg_entry = fetch_remote_ffmpeg_manifest()
    if not ffmpeg_entry:
        raise RuntimeError("FFmpeg download source is unavailable.")

    target_path = get_configured_ffmpeg_target_path()
    temp_path = f"{target_path}.part"
    ensure_folder_exists(target_path)

    source_label = _download_file_from_sources(
        ffmpeg_entry["sources"],
        temp_path,
        ffmpeg_entry.get("sha256", ""),
        progress_callback,
    )

    if os.path.exists(target_path):
        os.remove(target_path)
    os.replace(temp_path, target_path)

    config = load_config()
    config["ffmpeg_path"] = target_path
    save_config(config)

    return {"path": target_path, "source": source_label}


def _normalize_ffmpeg_entry(data, manifest_url):
    if not isinstance(data, dict):
        return None

    ffmpeg_data = data.get("ffmpeg")
    if not isinstance(ffmpeg_data, dict):
        return None

    name = str(ffmpeg_data.get("name", "ffmpeg.exe")).strip() or "ffmpeg.exe"
    sha256 = str(ffmpeg_data.get("sha256", "")).strip()
    sources = []

    if ffmpeg_data.get("url"):
        sources.append({"label": "primary", "url": str(ffmpeg_data["url"]).strip()})

    base_url = str(ffmpeg_data.get("base_url", "")).strip() or str(data.get("base_url", "")).strip()
    if base_url:
        sources.append({"label": "primary", "url": f"{base_url.rstrip('/')}/{name}"})

    mirrors = ffmpeg_data.get("mirrors")
    if not isinstance(mirrors, list):
        mirrors = data.get("mirrors", [])

    if isinstance(mirrors, list):
        for index, mirror in enumerate(mirrors, start=1):
            if isinstance(mirror, str) and mirror.strip():
                sources.append({"label": f"mirror-{index}", "url": f"{mirror.strip().rstrip('/')}/{name}"})
            elif isinstance(mirror, dict):
                base = str(mirror.get("base_url", "")).strip()
                if base:
                    sources.append(
                        {
                            "label": str(mirror.get("label", "")).strip() or f"mirror-{index}",
                            "url": f"{base.rstrip('/')}/{name}",
                        }
                    )

    deduped = []
    seen = set()
    for source in sources:
        url = source["url"]
        if not url or url in seen:
            continue
        deduped.append(source)
        seen.add(url)

    if not deduped:
        return None

    return {"name": name, "sha256": sha256, "sources": deduped}


def _download_file_from_sources(sources, target_path, expected_sha256="", progress_callback=None):
    errors = []
    for source in sources:
        label = source.get("label", "") or source.get("url", "")
        try:
            _download_file(source["url"], target_path, expected_sha256, progress_callback, label)
            return label
        except RuntimeError as exc:
            errors.append(f"{label}: {exc}")

    if os.path.exists(target_path):
        os.remove(target_path)
    raise RuntimeError("All FFmpeg download sources failed. " + " | ".join(errors))


def _download_file(url, target_path, expected_sha256="", progress_callback=None, source_label=""):
    return download_file(
        url,
        target_path,
        expected_sha256=expected_sha256,
        progress_callback=progress_callback,
        source_label=source_label,
        user_agent="VideoSeek/ffmpeg-download",
    )
