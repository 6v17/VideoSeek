"""Employee-side HTTP search / library discovery against a team server."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, List, Optional, Sequence

from src.app.logging_utils import get_logger
from src.domain.search_hit import SearchHit
from src.services.team_paths import normalize_http_base

logger = get_logger("team_client_search")

_VIDEO_PAGE_LIMIT = 2000


def _post_json(url: str, payload: dict, *, timeout: float = 120.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(_team_connect_error(url, exc)) from exc
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise RuntimeError("invalid team search response")
    return data


def _get_json(url: str, *, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(_team_connect_error(url, exc)) from exc
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise RuntimeError("invalid team API response")
    return data


def _team_connect_error(url: str, exc: BaseException) -> str:
    detail = str(getattr(exc, "reason", None) or exc)
    lower = detail.lower()
    if "getaddrinfo" in lower or "11001" in lower or "name or service not known" in lower:
        return (
            f"无法解析服务机地址。请填写局域网 IP，例如 http://192.168.1.10:8765（不要用电脑名除非同一网段可解析）。"
            f" 当前请求: {url}"
        )
    if "timed out" in lower or "timeout" in lower:
        return f"连接服务机超时（检查服务机是否已开启团队模式、防火墙是否放行 8765）。当前请求: {url}"
    if "10061" in lower or "refused" in lower:
        return f"服务机拒绝连接（确认服务机团队模式已应用且 API 在运行）。当前请求: {url}"
    return f"无法连接服务机。当前请求: {url}；错误: {detail}"


def _team_base(server_url: str, *, api_port_default: int = 8765) -> str:
    base = normalize_http_base(server_url, default_port=api_port_default)
    if not base:
        raise ValueError("team_server_url is empty")
    return base


def probe_team_server(server_url: str, *, api_port_default: int = 8765) -> dict:
    base = _team_base(server_url, api_port_default=api_port_default)
    return _get_json(f"{base}/api/v1/health?mode=summary", timeout=8.0)


def list_team_client_libraries(
    server_url: str,
    *,
    api_port_default: int = 8765,
    timeout: float = 30.0,
) -> List[dict]:
    """Return shared libraries from the team server (Agent API shape)."""
    base = _team_base(server_url, api_port_default=api_port_default)
    data = _get_json(f"{base}/api/v1/libraries", timeout=timeout)
    if data.get("ok") is False:
        err = data.get("error") or {}
        raise RuntimeError(str(err.get("message") or "team libraries failed"))
    rows = data.get("libraries") or []
    return [row for row in rows if isinstance(row, dict)]


def list_team_client_videos(
    server_url: str,
    *,
    library_path: Optional[str] = None,
    ready_only: bool = True,
    api_port_default: int = 8765,
    timeout: float = 60.0,
    page_limit: int = _VIDEO_PAGE_LIMIT,
) -> List[dict]:
    """Paginate through ready videos on the team server."""
    base = _team_base(server_url, api_port_default=api_port_default)
    out: List[dict] = []
    offset = 0
    safe_limit = max(1, min(int(page_limit or _VIDEO_PAGE_LIMIT), _VIDEO_PAGE_LIMIT))
    while True:
        params: dict[str, str] = {
            "ready_only": "true" if ready_only else "false",
            "limit": str(safe_limit),
            "offset": str(offset),
        }
        if library_path:
            params["library_path"] = str(library_path)
        query = urllib.parse.urlencode(params)
        data = _get_json(f"{base}/api/v1/libraries/videos?{query}", timeout=timeout)
        if data.get("ok") is False:
            err = data.get("error") or {}
            raise RuntimeError(str(err.get("message") or "team videos failed"))
        page = data.get("videos") or []
        if not isinstance(page, list) or not page:
            break
        for row in page:
            if isinstance(row, dict):
                out.append(row)
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        total = int(meta.get("total_listed") or 0)
        offset += len(page)
        if offset >= total or len(page) < safe_limit:
            break
    return out


def list_team_client_scope_entries(
    server_url: str,
    *,
    api_port_default: int = 8765,
) -> List[dict]:
    """Build scope-tree entries from the shared server library (server absolute paths)."""
    libraries = list_team_client_libraries(server_url, api_port_default=api_port_default)
    entries: List[dict] = []
    for lib in libraries:
        lib_path = str(lib.get("library_path") or "").strip()
        if not lib_path:
            continue
        try:
            videos = list_team_client_videos(
                server_url,
                library_path=lib_path,
                ready_only=True,
                api_port_default=api_port_default,
            )
        except Exception:
            logger.exception("Failed listing team videos for %s", lib_path)
            continue
        for row in videos:
            video_path = str(row.get("video_path") or "").strip()
            rel = str(row.get("video_rel_path") or "").strip()
            video_id = str(row.get("video_id") or "").strip()
            if not video_path or not video_id:
                continue
            # Server already filtered ready; treat as present for the client scope picker.
            entries.append(
                {
                    "library_path": str(row.get("library_path") or lib_path),
                    "video_path": video_path,
                    "video_rel_path": rel,
                    "video_id": video_id,
                    "abs_path": video_path,
                    "source_exists": True,
                    "asset_state": "ready",
                    "team_shared": True,
                }
            )
    return entries


def list_team_client_library_tree(
    server_url: str,
    *,
    api_port_default: int = 8765,
) -> tuple[List[dict], List[str]]:
    """Entries + library roots for the library page (read-only shared view)."""
    libraries = list_team_client_libraries(server_url, api_port_default=api_port_default)
    library_paths = [str(lib.get("library_path") or "").strip() for lib in libraries]
    library_paths = [p for p in library_paths if p]
    entries = list_team_client_scope_entries(server_url, api_port_default=api_port_default)
    # Enrich status text fields expected by library tree
    for item in entries:
        item.setdefault("status_text", "ready")
        item.setdefault("status_tone", "ready")
    return entries, library_paths


def _encode_image_query(query_data) -> Optional[dict]:
    """Build Agent API image query payload from path / bytes / ndarray-ish."""
    if query_data is None:
        return None
    if isinstance(query_data, str):
        path = query_data.strip()
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"image not found: {path}")
        with open(path, "rb") as handle:
            raw = handle.read()
        ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
        mime = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "bmp": "image/bmp",
            "gif": "image/gif",
        }.get(ext, "application/octet-stream")
        return {
            "query_type": "image",
            "image_base64": base64.b64encode(raw).decode("ascii"),
            "image_mime": mime,
        }
    try:
        import cv2
        import numpy as np

        if isinstance(query_data, np.ndarray):
            ok, buf = cv2.imencode(".png", query_data)
            if not ok:
                raise RuntimeError("failed to encode query image")
            raw = buf.tobytes()
            return {
                "query_type": "image",
                "image_base64": base64.b64encode(raw).decode("ascii"),
                "image_mime": "image/png",
            }
    except Exception:
        logger.exception("Failed encoding team image query")
        raise
    raise TypeError(f"unsupported image query type: {type(query_data).__name__}")


def run_team_client_search(
    *,
    server_url: str,
    query_data,
    is_text: bool,
    search_mode: Optional[str] = None,
    search_precision_mode: Optional[str] = None,
    top_k: Optional[int] = None,
    scope_video_paths: Optional[Sequence[str]] = None,
    scope_library_paths: Optional[Sequence[str]] = None,
    api_port_default: int = 8765,
    timeout: float = 180.0,
) -> List[SearchHit]:
    base = _team_base(server_url, api_port_default=api_port_default)

    payload: dict[str, Any] = {
        "expand_frame_hits": True,
        "team_play_urls": True,
    }
    if top_k is not None:
        payload["top_k"] = int(top_k)
    mode = str(search_mode or "").strip().lower()
    if mode in {"frame", "chunk"}:
        payload["search_mode"] = mode
    precision = str(search_precision_mode or "").strip().lower()
    if precision:
        payload["search_precision_mode"] = precision

    video_paths = [str(p).strip() for p in (scope_video_paths or []) if str(p or "").strip()]
    library_paths = [str(p).strip() for p in (scope_library_paths or []) if str(p or "").strip()]
    if video_paths or library_paths:
        scope: dict[str, Any] = {"use_saved_scope": False}
        if video_paths:
            scope["video_paths"] = video_paths
        if library_paths and not video_paths:
            scope["library_paths"] = library_paths
        payload["scope"] = scope

    if is_text:
        payload["query_type"] = "text"
        payload["query"] = str(query_data or "")
    else:
        payload.update(_encode_image_query(query_data) or {})

    data = _post_json(f"{base}/api/v1/search", payload, timeout=timeout)
    if data.get("ok") is False:
        err = data.get("error") or {}
        raise RuntimeError(str(err.get("message") or data.get("message") or "team search failed"))

    hits_raw = data.get("hits") or data.get("results") or []
    out: List[SearchHit] = []
    if not isinstance(hits_raw, list):
        return out
    for row in hits_raw:
        if not isinstance(row, dict):
            continue
        play = str(row.get("play_url") or "").strip()
        path = play or str(row.get("video_path") or "").strip()
        if not path:
            continue
        out.append(
            SearchHit(
                start_sec=float(row.get("start_sec") or 0.0),
                end_sec=float(row.get("end_sec") or 0.0),
                score=float(row.get("score") or 0.0),
                video_path=path,
                match_kind=str(row.get("match_kind") or "frame"),
                video_id=str(row.get("video_id") or ""),
                matched_text=str(row.get("matched_text") or ""),
            )
        )
    return out
