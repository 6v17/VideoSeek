import json

from src.app.app_meta import get_app_meta
from src.app.config import get_app_version
from src.app.i18n import get_texts
from src.services.remote_fetch_cache import DEFAULT_REMOTE_USER_AGENT, fetch_cached_text


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
    compare = _compare_versions(latest_version, current_version)
    has_update = compare > 0
    if has_update:
        status_text = texts["version_update_available"].format(version=latest_version)
    elif compare == 0:
        status_text = texts["version_up_to_date"].format(version=current_version)
    else:
        status_text = texts["version_label"].format(version=current_version)
    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "status_text": status_text,
        "download_url": download_url,
        "has_update": has_update,
    }


def fetch_remote_version():
    app_meta = get_app_meta()
    version_url = app_meta.get("version_url", "").strip()
    if not version_url:
        return None

    try:
        raw_text = fetch_cached_text(version_url, kind="json", user_agent=DEFAULT_REMOTE_USER_AGENT)
        if not raw_text:
            return None
        data = json.loads(raw_text)
    except (json.JSONDecodeError, UnicodeDecodeError):
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
