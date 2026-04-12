import json
import os
import urllib.error
import urllib.request

from src.app.app_meta import get_app_meta
from src.app.config import load_config
from src.services.download_utils import download_file


def get_remote_index_status():
    config = load_config()
    index_file = config.get("remote_index_file", "")
    vector_file = config.get("remote_vector_file", "")
    manifest_url = str(get_app_meta().get("remote_index_manifest_url", "")).strip()
    return {
        "ready": bool(index_file and vector_file and os.path.exists(index_file) and os.path.exists(vector_file)),
        "index_file": index_file,
        "vector_file": vector_file,
        "download_enabled": bool(manifest_url),
    }


def fetch_remote_index_manifest():
    app_meta = get_app_meta()
    manifest_url = str(app_meta.get("remote_index_manifest_url", "")).strip()
    timeout = int(app_meta.get("remote_timeout", 4))
    if not manifest_url:
        return None

    request = urllib.request.Request(manifest_url, headers={"User-Agent": "VideoSeek/remote-index"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    files = data.get("files")
    if not isinstance(files, list) or not files:
        return None
    normalized = []
    for item in files:
        if not isinstance(item, dict):
            return None
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not name or not url:
            return None
        normalized.append({"name": name, "url": url, "sha256": str(item.get("sha256", "")).strip()})
    return {"files": normalized}


def download_remote_index_pack(progress_callback=None):
    # Retained intentionally: not wired to the current UI, but still serves as
    # the remote index pack download entrypoint for future UI or script usage.
    manifest = fetch_remote_index_manifest()
    if not manifest:
        raise RuntimeError("Remote index manifest is unavailable.")

    config = load_config()
    target_by_name = {
        os.path.basename(config.get("remote_index_file", "")): config.get("remote_index_file", ""),
        os.path.basename(config.get("remote_vector_file", "")): config.get("remote_vector_file", ""),
    }
    targets = []
    for file_info in manifest["files"]:
        name = file_info["name"]
        target_path = target_by_name.get(name)
        if target_path:
            targets.append((file_info, target_path))
    if not targets:
        raise RuntimeError("Manifest does not contain required remote index files.")

    total = len(targets)
    for idx, (file_info, target_path) in enumerate(targets, start=1):
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        temp_path = f"{target_path}.part"
        base = int((idx - 1) / total * 100)
        span = max(1, int(100 / total))
        _emit(progress_callback, base, f"Preparing {file_info['name']}...")
        _download_file(
            file_info["url"],
            temp_path,
            expected_sha256=file_info.get("sha256", ""),
            progress_callback=lambda current, total_size: _emit_download_progress(
                progress_callback, base, span, file_info["name"], current, total_size
            ),
        )
        if os.path.exists(target_path):
            os.remove(target_path)
        os.replace(temp_path, target_path)
        _emit(progress_callback, min(99, base + span), f"Downloaded {file_info['name']}")
    _emit(progress_callback, 100, "Remote index is ready.")
    return get_remote_index_status()


def _download_file(url, target_path, expected_sha256="", progress_callback=None):
    return download_file(
        url,
        target_path,
        expected_sha256=expected_sha256,
        progress_callback=lambda current, total_size, _label: progress_callback(current, total_size)
        if progress_callback else None,
        user_agent="VideoSeek/remote-index-download",
    )


def _emit_download_progress(progress_callback, base, span, file_name, current, total_size):
    if not progress_callback:
        return
    if total_size > 0:
        ratio = min(100, int((current / total_size) * 100))
        value = min(99, base + int((ratio / 100) * span))
        text = f"Downloading {file_name} ({_format_bytes(current)}/{_format_bytes(total_size)})"
    else:
        value = min(99, base + max(1, span // 2))
        text = f"Downloading {file_name} ({_format_bytes(current)})"
    progress_callback(value, text)


def _emit(progress_callback, value, text):
    if progress_callback:
        progress_callback(int(value), str(text))


def _format_bytes(value):
    units = ["B", "KB", "MB", "GB"]
    size = float(value or 0)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024
