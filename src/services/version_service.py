import json
import urllib.error
import urllib.request

from src.app.app_meta import get_app_meta
from src.app.config import get_app_version
from src.app.i18n import get_texts


def get_local_version_status(language):
    texts = get_texts(language)
    current_version = get_app_version()
    return {
        "current_version": current_version,
        "latest_version": current_version,
        "status_text": texts["version_check_unavailable"],
        "download_url": "",
        "has_update": False,
    }


def get_version_status(language):
    texts = get_texts(language)
    current_version = get_app_version()
    remote_data = fetch_remote_version()
    if not remote_data:
        return get_local_version_status(language)

    latest_version = str(remote_data.get("version") or current_version)
    download_url = str(remote_data.get("download_url") or "")
    has_update = _compare_versions(latest_version, current_version) > 0
    status_key = "version_update_available" if has_update else "version_up_to_date"
    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "status_text": texts[status_key].format(version=latest_version),
        "download_url": download_url,
        "has_update": has_update,
    }


def fetch_remote_version():
    app_meta = get_app_meta()
    version_url = app_meta.get("version_url", "").strip()
    timeout = app_meta.get("remote_timeout", 4)
    if not version_url:
        return None

    request = urllib.request.Request(
        version_url,
        headers={"User-Agent": "VideoSeek/version-check"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict):
        return None
    return data


def _compare_versions(left, right):
    left_parts = _parse_version(left)
    right_parts = _parse_version(right)
    max_len = max(len(left_parts), len(right_parts))
    left_parts += [0] * (max_len - len(left_parts))
    right_parts += [0] * (max_len - len(right_parts))
    if left_parts > right_parts:
        return 1
    if left_parts < right_parts:
        return -1
    return 0


def _parse_version(version_text):
    core = str(version_text).strip().lstrip("vV")
    parts = []
    for piece in core.split("."):
        number = "".join(char for char in piece if char.isdigit())
        parts.append(int(number or 0))
    return parts or [0]
