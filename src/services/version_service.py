import json
import re
from dataclasses import dataclass

from src.app.app_meta import get_app_meta
from src.app.config import get_app_version
from src.app.i18n import get_texts
from src.services.remote_fetch_cache import DEFAULT_REMOTE_USER_AGENT, fetch_cached_text

# 1.0.88 | 1.0.88-beta.1 | v1.0.88-beta2
_VERSION_RE = re.compile(
    r"^v?(?P<release>\d+(?:\.\d+)*)"
    r"(?:-(?P<pre_label>[a-zA-Z]+)"
    r"(?:[.\-]?(?P<pre_num>\d+))?)?"
    r"$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedVersion:
    """Product version key. Same release: final (prerelease=None) > any prerelease."""

    release: tuple[int, ...]
    prerelease: tuple[str, int] | None  # e.g. ("beta", 1)


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


def is_prerelease(version_text: str) -> bool:
    return _parse_version(version_text).prerelease is not None


def _compare_versions(left, right):
    left_parsed = _parse_version(left)
    right_parsed = _parse_version(right)
    left_release = _pad_release(left_parsed.release, right_parsed.release)
    right_release = _pad_release(right_parsed.release, left_parsed.release)
    if left_release > right_release:
        return 1
    if left_release < right_release:
        return -1

    left_pre = left_parsed.prerelease
    right_pre = right_parsed.prerelease
    if left_pre is None and right_pre is None:
        return 0
    # Final release sorts after any prerelease of the same base.
    if left_pre is None:
        return 1
    if right_pre is None:
        return -1
    if left_pre > right_pre:
        return 1
    if left_pre < right_pre:
        return -1
    return 0


def _pad_release(parts: tuple[int, ...], other: tuple[int, ...]) -> tuple[int, ...]:
    width = max(len(parts), len(other), 1)
    return tuple(list(parts) + [0] * (width - len(parts)))


def _parse_version(version_text) -> ParsedVersion:
    raw = str(version_text or "").strip()
    match = _VERSION_RE.match(raw)
    if match:
        release = tuple(int(piece) for piece in match.group("release").split("."))
        label = match.group("pre_label")
        if label:
            pre_num = int(match.group("pre_num") or 0)
            return ParsedVersion(release=release or (0,), prerelease=(label.lower(), pre_num))
        return ParsedVersion(release=release or (0,), prerelease=None)

    # Fallback: digit runs only (legacy noisy strings).
    core = raw.lstrip("vV")
    parts: list[int] = []
    for piece in core.split("."):
        number = "".join(char for char in piece if char.isdigit())
        if number:
            parts.append(int(number))
    return ParsedVersion(release=tuple(parts) or (0,), prerelease=None)
