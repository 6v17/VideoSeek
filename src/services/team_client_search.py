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
_TEAM_ENGINE_BUSY_MARKER = "TEAM_ENGINE_BUSY"


class TeamSearchBusyError(RuntimeError):
    """Team server rejected the search because the concurrency queue was full."""

    def __init__(self, message: str = ""):
        detail = str(message or "").strip()
        super().__init__(f"{_TEAM_ENGINE_BUSY_MARKER}:{detail}" if detail else _TEAM_ENGINE_BUSY_MARKER)


def is_team_search_busy_error(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    if raw.startswith(_TEAM_ENGINE_BUSY_MARKER) or _TEAM_ENGINE_BUSY_MARKER in raw:
        return True
    lower = raw.lower()
    return "search engine is busy" in lower or "engine_busy" in lower


def _raise_from_http_error(exc: urllib.error.HTTPError) -> None:
    raw = ""
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:
        raw = ""
    data: dict = {}
    try:
        parsed = json.loads(raw or "{}")
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        data = {}
    err = data.get("error") if isinstance(data.get("error"), dict) else {}
    code = str(err.get("code") or "").strip().lower()
    message = str(err.get("message") or "").strip() or str(exc.reason or raw or "team request failed")
    if code == "engine_busy" or int(getattr(exc, "code", 0) or 0) == 503:
        raise TeamSearchBusyError(message)
    raise RuntimeError(message)


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
    except urllib.error.HTTPError as exc:
        _raise_from_http_error(exc)
        raise
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise RuntimeError("invalid team search response")
    return data


def _get_json(url: str, *, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise RuntimeError("invalid team API response")
    return data


def _team_base(server_url: str, *, api_port_default: int = 8765) -> str:
    base = normalize_http_base(server_url, default_port=api_port_default)
    if not base:
        raise ValueError("team_server_url is empty")
    return base


def _browse_url_from_http_play_url(text: str) -> str:
    """http://host:port/videos/<libid>/rel/file.mp4 → library root listing URL."""
    parsed = urllib.parse.urlparse(text)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "videos":
        folder = "/" + "/".join(parts[:2]) + "/"
        return urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, folder, "", "", "")
        )
    if text.endswith("/"):
        return text
    parent = text.rstrip("/").rsplit("/", 1)[0]
    return parent + "/" if parent else text


def resolve_team_library_browse_url(
    path_or_url: str,
    *,
    server_url: str = "",
    api_port_default: int = 8765,
) -> str:
    """Turn a team play URL / server path hint into a browser library folder URL."""
    text = str(path_or_url or "").strip()
    if not text:
        return ""
    if text.lower().startswith(("http://", "https://")):
        return _browse_url_from_http_play_url(text)

    # Server absolute path on the employee machine → map via health mounts.
    if not str(server_url or "").strip():
        return ""
    try:
        from src.services.team_media_map import absolute_path_to_library_browse_url

        base = _team_base(server_url, api_port_default=api_port_default)
        health = _get_json(f"{base}/api/v1/health", timeout=8.0)
        team = health.get("team") if isinstance(health.get("team"), dict) else {}
        mounts = team.get("mounts") or []
        media_base = str(team.get("media_base_url") or "").strip()
        if not media_base or not isinstance(mounts, list):
            return ""
        return absolute_path_to_library_browse_url(
            text,
            mounts,
            media_base_url=media_base,
        )
    except Exception:
        logger.exception("resolve_team_library_browse_url failed for %s", text)
        return ""


def probe_team_server(server_url: str, *, api_port_default: int = 8765) -> dict:
    """Cheap connectivity check — uses health ping, not a full index snapshot."""
    base = _team_base(server_url, api_port_default=api_port_default)
    url = f"{base}/api/v1/health?mode=ping"
    parsed = urllib.parse.urlparse(base)
    port_text = str(parsed.port or api_port_default)
    try:
        return _get_json(url, timeout=5.0)
    except urllib.error.HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        raise RuntimeError(
            f"服务机有响应但返回 HTTP {code}：{base}。"
            "请确认对方是 VideoSeek「服务机」模式，且版本兼容。"
        ) from exc
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", "") or exc).strip() or "network error"
        raise RuntimeError(
            f"无法连接服务机 {base}（{reason}）。\n"
            "请确认：\n"
            "1) 对方已选「本机作为服务机」并已保存，状态显示服务机已启动；\n"
            f"2) 填写的地址/端口正确（当前端口 {port_text}）；\n"
            "3) 两台电脑同一局域网（手机热点/访客 Wi‑Fi 常隔离）；\n"
            f"4) 服务机防火墙放行入站 TCP {port_text}（以及视频端口，默认 18080）。"
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"连接服务机超时：{base}。\n"
            f"请检查对方是否在线、地址/端口（{port_text}）是否正确、防火墙是否放行。"
        ) from exc


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


def list_team_client_subtitle_libraries(
    server_url: str,
    *,
    api_port_default: int = 8765,
    timeout: float = 30.0,
) -> List[dict]:
    base = _team_base(server_url, api_port_default=api_port_default)
    data = _get_json(f"{base}/api/v1/subtitle-libraries", timeout=timeout)
    if data.get("ok") is False:
        err = data.get("error") or {}
        raise RuntimeError(str(err.get("message") or "team subtitle libraries failed"))
    rows = data.get("libraries") or []
    return [row for row in rows if isinstance(row, dict)]


def list_team_client_subtitle_videos(
    server_url: str,
    *,
    library_path: Optional[str] = None,
    ready_only: bool = True,
    api_port_default: int = 8765,
    timeout: float = 60.0,
    page_limit: int = _VIDEO_PAGE_LIMIT,
) -> List[dict]:
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
        data = _get_json(f"{base}/api/v1/subtitle-libraries/videos?{query}", timeout=timeout)
        if data.get("ok") is False:
            err = data.get("error") or {}
            raise RuntimeError(str(err.get("message") or "team subtitle videos failed"))
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


def list_team_client_subtitle_scope_entries(
    server_url: str,
    *,
    api_port_default: int = 8765,
) -> List[dict]:
    """Subtitle/dialogue scope entries from the team server."""
    # Prefer one unscoped listing — avoids Windows path key mismatches per library.
    try:
        videos = list_team_client_subtitle_videos(
            server_url,
            library_path=None,
            ready_only=False,
            api_port_default=api_port_default,
        )
    except Exception:
        logger.exception("Failed listing all team subtitle videos; falling back per library")
        videos = []
        libraries = list_team_client_subtitle_libraries(
            server_url, api_port_default=api_port_default
        )
        for lib in libraries:
            lib_path = str(lib.get("library_path") or "").strip()
            if not lib_path:
                continue
            try:
                videos.extend(
                    list_team_client_subtitle_videos(
                        server_url,
                        library_path=lib_path,
                        ready_only=False,
                        api_port_default=api_port_default,
                    )
                )
            except Exception:
                logger.exception("Failed listing team subtitle videos for %s", lib_path)

    entries: List[dict] = []
    seen_ids: set[str] = set()
    for row in videos:
        if not isinstance(row, dict):
            continue
        video_path = str(row.get("video_path") or "").strip()
        video_id = str(row.get("video_id") or "").strip()
        if not video_path or not video_id or video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        has_transcript = bool(row.get("has_transcript"))
        asset_state = str(row.get("asset_state") or "").strip().lower()
        if not asset_state:
            asset_state = "ready" if has_transcript else "pending"
        entries.append(
            {
                "library_path": str(row.get("library_path") or "").strip(),
                "video_path": video_path,
                "video_rel_path": str(row.get("video_rel_path") or "").strip(),
                "video_id": video_id,
                "abs_path": video_path,
                # Shared remote view: never hide rows because the client cannot
                # see the server's local filesystem.
                "source_exists": True,
                "has_transcript": has_transcript,
                "asset_state": asset_state,
                "team_shared": True,
            }
        )
    return entries


def list_team_client_subtitle_library_tree(
    server_url: str,
    *,
    api_port_default: int = 8765,
) -> tuple[List[dict], List[str]]:
    libraries = list_team_client_subtitle_libraries(server_url, api_port_default=api_port_default)
    library_paths = [str(lib.get("library_path") or "").strip() for lib in libraries]
    library_paths = [p for p in library_paths if p]
    entries = list_team_client_subtitle_scope_entries(
        server_url, api_port_default=api_port_default
    )
    for item in entries:
        has_transcript = bool(item.get("has_transcript"))
        item.setdefault("status_text", "ready" if has_transcript else "pending")
        item.setdefault("status_tone", "ready" if has_transcript else "pending")
    return entries, library_paths


def prepare_team_client_session(
    server_url: str,
    *,
    api_port_default: int = 8765,
) -> dict:
    """Probe + preload visual/subtitle trees for a smooth first connect."""
    probe_team_server(server_url, api_port_default=api_port_default)
    visual_entries, visual_paths = list_team_client_library_tree(
        server_url, api_port_default=api_port_default
    )
    try:
        subtitle_entries, subtitle_paths = list_team_client_subtitle_library_tree(
            server_url, api_port_default=api_port_default
        )
    except Exception:
        logger.exception("Team subtitle library preload failed")
        subtitle_entries, subtitle_paths = [], []
    return {
        "visual_entries": visual_entries,
        "visual_library_paths": visual_paths,
        "subtitle_entries": subtitle_entries,
        "subtitle_library_paths": subtitle_paths,
    }


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
    search_kind: Optional[str] = None,
    top_k: Optional[int] = None,
    scope_video_paths: Optional[Sequence[str]] = None,
    scope_library_paths: Optional[Sequence[str]] = None,
    video_discovery_enabled: Optional[bool] = None,
    preview_anchor_sec: Optional[float] = None,
    api_port_default: int = 8765,
    timeout: float = 180.0,
) -> List[SearchHit]:
    base = _team_base(server_url, api_port_default=api_port_default)

    payload: dict[str, Any] = {
        # Keep expand for clip/export helpers on the server, but rebuild
        # employee SearchHits from raw_* so frame mode still shows 帧.
        "expand_frame_hits": True,
        "team_play_urls": True,
    }
    kind = str(search_kind or "").strip().lower()
    if kind == "dialogue":
        payload["search_kind"] = "dialogue"
        payload["expand_frame_hits"] = False
    if top_k is not None:
        payload["top_k"] = int(top_k)
    mode = str(search_mode or "").strip().lower()
    if kind != "dialogue" and mode in {"frame", "chunk"}:
        # Send both keys: older servers only read `mode`; `search_mode` is the team alias.
        payload["mode"] = mode
        payload["search_mode"] = mode
    precision = str(search_precision_mode or "").strip().lower()
    if precision:
        payload["search_precision_mode"] = precision
    if video_discovery_enabled is not None and kind != "dialogue":
        payload["video_discovery_enabled"] = bool(video_discovery_enabled)
    if preview_anchor_sec is not None and kind != "dialogue":
        try:
            payload["preview_anchor_sec"] = max(0.0, float(preview_anchor_sec))
        except (TypeError, ValueError):
            pass

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
        if kind == "dialogue":
            raise RuntimeError("dialogue search only supports text queries")
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
        start_sec, end_sec = _team_hit_time_range(row, preferred_mode=mode)
        match_kind = str(row.get("match_kind") or "").strip().lower()
        if not match_kind:
            if kind == "dialogue":
                match_kind = "dialogue"
            elif mode == "chunk":
                match_kind = "chunk"
            else:
                match_kind = "frame"
        out.append(
            SearchHit(
                start_sec=start_sec,
                end_sec=end_sec,
                score=float(row.get("score") or 0.0),
                video_path=path,
                match_kind=match_kind,
                video_id=str(row.get("video_id") or ""),
                matched_text=str(row.get("matched_text") or ""),
            )
        )
    return out


def _team_hit_time_range(row: dict, *, preferred_mode: str = "") -> tuple[float, float]:
    """Prefer raw match times so expanded clip windows do not hide frame-level hits."""
    _ = preferred_mode
    clip = row.get("clip_window") if isinstance(row.get("clip_window"), dict) else {}
    raw_start = row.get("raw_start_sec", clip.get("raw_start_sec"))
    raw_end = row.get("raw_end_sec", clip.get("raw_end_sec"))
    if raw_start is not None and raw_end is not None:
        try:
            return float(raw_start), float(raw_end)
        except (TypeError, ValueError):
            pass
    try:
        return float(row.get("start_sec") or 0.0), float(row.get("end_sec") or 0.0)
    except (TypeError, ValueError):
        return 0.0, 0.0
