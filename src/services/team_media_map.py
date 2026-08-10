"""Map library folders to nginx /videos/<id>/ URL prefixes."""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional

from src.services.search_scope import normalize_scope_path


def _stable_lib_id(library_path: str) -> str:
    norm = normalize_scope_path(library_path) or str(library_path or "").strip()
    digest = hashlib.sha1(norm.encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"lib{digest}"


def _nginx_alias_path(library_path: str) -> str:
    """Windows-friendly absolute path for nginx alias (forward slashes, trailing /)."""
    abs_path = os.path.abspath(str(library_path or "").strip())
    abs_path = abs_path.replace("\\", "/")
    if abs_path and not abs_path.endswith("/"):
        abs_path += "/"
    return abs_path


def build_media_mounts(library_paths: List[str]) -> List[Dict[str, str]]:
    mounts: List[Dict[str, str]] = []
    seen: set[str] = set()
    for raw in library_paths or []:
        path = str(raw or "").strip()
        if not path:
            continue
        norm = normalize_scope_path(path) or os.path.abspath(path)
        if norm in seen:
            continue
        if not os.path.isdir(path):
            continue
        seen.add(norm)
        lib_id = _stable_lib_id(norm)
        mounts.append(
            {
                "id": lib_id,
                "library_path": os.path.abspath(path),
                "alias": _nginx_alias_path(path),
                "url_prefix": f"/videos/{lib_id}/",
            }
        )
    return mounts


def absolute_path_to_play_url(
    video_path: str,
    mounts: List[Dict[str, str]],
    *,
    media_base_url: str,
) -> str:
    """Rewrite an absolute file path to http://host:port/videos/<id>/rel."""
    from urllib.parse import quote

    base = str(media_base_url or "").strip().rstrip("/")
    abs_video = os.path.abspath(str(video_path or "").strip())
    if not base or not abs_video:
        return ""
    mount = _best_mount_for_path(abs_video, mounts)
    if mount is None:
        return ""
    rel = _relative_under_mount(abs_video, mount)
    if rel is None:
        return ""
    prefix = str(mount.get("url_prefix") or f"/videos/{mount.get('id')}/").rstrip("/") + "/"
    # Encode [ ] spaces etc. Browsers tolerate raw brackets; VLC/ffmpeg often do not.
    rel_url = "/".join(quote(part, safe="") for part in rel.replace("\\", "/").split("/"))
    return f"{base}{prefix}{rel_url}"


def play_url_to_absolute_path(play_url: str, mounts: List[Dict[str, str]]) -> str:
    """Reverse of absolute_path_to_play_url: http://host/videos/<id>/rel → abs path."""
    from urllib.parse import unquote, urlparse

    text = str(play_url or "").strip()
    if not text:
        return ""
    if not text.lower().startswith(("http://", "https://")):
        return text
    parsed = urlparse(text)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or parts[0].lower() != "videos":
        return ""
    lib_id = str(parts[1] or "").strip()
    rel = unquote("/".join(parts[2:]))
    if not lib_id:
        return ""
    for mount in mounts or []:
        if str(mount.get("id") or "").strip() != lib_id:
            continue
        root = str(mount.get("library_path") or "").strip()
        if not root:
            continue
        if not rel:
            return os.path.abspath(root)
        return os.path.normpath(os.path.join(os.path.abspath(root), rel.replace("/", os.sep)))
    return ""


def rewrite_team_scope_video_paths(
    video_paths: Optional[List[str]],
    mounts: Optional[List[Dict[str, str]]] = None,
) -> Optional[List[str]]:
    """Map team play_url scope entries back to server-local filesystem paths."""
    if not video_paths:
        return video_paths
    active = list(mounts) if mounts is not None else []
    if not active:
        try:
            from src.services.team_mode_service import get_active_media_mounts, list_local_library_paths

            active = get_active_media_mounts()
            if not active:
                active = build_media_mounts(list_local_library_paths())
        except Exception:
            active = []
    out: List[str] = []
    for raw in video_paths:
        text = str(raw or "").strip()
        if not text:
            continue
        if text.lower().startswith(("http://", "https://")):
            mapped = play_url_to_absolute_path(text, active)
            out.append(mapped or text)
        else:
            out.append(text)
    return out or None


def absolute_path_to_library_browse_url(
    video_or_library_path: str,
    mounts: List[Dict[str, str]],
    *,
    media_base_url: str,
) -> str:
    """HTTP URL for the shared library folder that contains *video_or_library_path*."""
    text = str(video_or_library_path or "").strip()
    if text.lower().startswith(("http://", "https://")):
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(text)
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 2 and path_parts[0].lower() == "videos":
            folder = "/" + "/".join(path_parts[:2]) + "/"
            return urlunparse((parsed.scheme, parsed.netloc, folder, "", "", ""))
        if "/" in text.rstrip("/"):
            return text.rstrip("/").rsplit("/", 1)[0] + "/"
        return text

    base = str(media_base_url or "").strip().rstrip("/")
    abs_path = os.path.abspath(text) if text else ""
    if not base or not abs_path:
        return ""
    mount = _best_mount_for_path(abs_path, mounts)
    if mount is None:
        return ""
    prefix = str(mount.get("url_prefix") or f"/videos/{mount.get('id')}/").rstrip("/") + "/"
    return f"{base}{prefix}"


def _best_mount_for_path(abs_video: str, mounts: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    abs_norm = abs_video.replace("\\", "/")
    best: Optional[Dict[str, str]] = None
    best_len = -1
    for mount in mounts or []:
        root = str(mount.get("library_path") or "").strip()
        if not root:
            continue
        root_norm = os.path.abspath(root).replace("\\", "/")
        if not root_norm.endswith("/"):
            root_norm += "/"
        candidate = abs_norm if abs_norm.endswith("/") else abs_norm
        # Compare case-insensitive on Windows
        if os.name == "nt":
            if not candidate.lower().startswith(root_norm.rstrip("/").lower()):
                root_cmp = root_norm.rstrip("/").lower()
                cand_cmp = candidate.lower()
                if cand_cmp != root_cmp and not cand_cmp.startswith(root_cmp + "/"):
                    continue
            length = len(root_norm)
        else:
            if candidate != root_norm.rstrip("/") and not candidate.startswith(root_norm):
                continue
            length = len(root_norm)
        if length > best_len:
            best = mount
            best_len = length
    return best


def _relative_under_mount(abs_video: str, mount: Dict[str, str]) -> Optional[str]:
    abs_norm = abs_video.replace("\\", "/")
    root_abs = os.path.abspath(str(mount["library_path"])).replace("\\", "/")
    if not root_abs.endswith("/"):
        root_abs += "/"
    rel = abs_norm
    if os.name == "nt":
        if rel.lower().startswith(root_abs.lower()):
            rel = rel[len(root_abs) :]
        else:
            root_cmp = root_abs.rstrip("/").lower()
            if rel.lower().startswith(root_cmp + "/"):
                rel = rel[len(root_cmp) + 1 :]
            elif rel.lower() == root_cmp:
                rel = ""
            else:
                return None
    else:
        if not rel.startswith(root_abs):
            return None
        rel = rel[len(root_abs) :]
    return rel.lstrip("/")


def mounts_public_payload(mounts: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": m["id"],
            "library_path": m["library_path"],
            "url_prefix": m["url_prefix"],
            "display_name": os.path.basename(os.path.normpath(m["library_path"])) or m["id"],
        }
        for m in mounts
    ]
