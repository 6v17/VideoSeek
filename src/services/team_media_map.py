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
    base = str(media_base_url or "").strip().rstrip("/")
    abs_video = os.path.abspath(str(video_path or "").strip())
    if not base or not abs_video:
        return ""
    abs_norm = abs_video.replace("\\", "/")
    # Longest prefix wins
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
                # also allow without trailing compare
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
    if best is None:
        return ""
    root_abs = os.path.abspath(str(best["library_path"])).replace("\\", "/")
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
                return ""
    else:
        if not rel.startswith(root_abs):
            return ""
        rel = rel[len(root_abs) :]
    rel = rel.lstrip("/")
    prefix = str(best.get("url_prefix") or f"/videos/{best.get('id')}/").rstrip("/") + "/"
    return f"{base}{prefix}{rel}"


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
