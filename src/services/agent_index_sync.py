"""Start a desktop library sync from the Agent API.

The handler is registered by the running window. It scans libraries that
already exist and then indexes new or changed videos. It does not add a folder.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable, Dict, List, Optional

from src.web.agent_api.constants import API_VERSION

Handler = Callable[[List[str]], Dict[str, Any]]
AddHandler = Callable[[str], Dict[str, Any]]

_MAX_SYNC_VIDEOS = 2000

_lock = threading.Lock()
_handler: Optional[Handler] = None
_add_handler: Optional[AddHandler] = None
_refresh_handler: Optional[Handler] = None
_include_handler: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None

_STATUS = {
    "unknown_library": 400,
    "unknown_video": 400,
    "video_outside_library": 400,
    "video_selection_empty": 400,
    "too_many_videos": 400,
    "no_libraries": 400,
    "library_path_required": 400,
    "invalid_library_path": 400,
    "invalid_video_path": 400,
    "team_client": 403,
    "already_running": 409,
    "library_exists": 409,
    "library_overlap": 409,
    "migration_busy": 409,
    "model_unavailable": 503,
    "desktop_unavailable": 503,
    "desktop_timeout": 503,
    "failed": 500,
}

_MESSAGES = {
    "unknown_library": "library_path is not a known visual library. Use GET /libraries.",
    "unknown_video": "That video is not in the last library scan. POST /libraries/refresh, then GET /videos?ready_only=false.",
    "video_outside_library": "That video is not in library_path.",
    "video_selection_empty": "video_ids or video_paths is empty.",
    "too_many_videos": "At most 2000 videos per sync.",
    "no_libraries": "No visual libraries are configured.",
    "library_path_required": "library_path is required.",
    "invalid_library_path": "library_path must be an existing absolute folder.",
    "invalid_video_path": "video_path must be an existing absolute video file.",
    "library_exists": "That folder is already a library. POST /index/sync to pick up new files.",
    "library_overlap": "That folder overlaps an existing library.",
    "team_client": "Team clients cannot sync. Sync on the server machine.",
    "already_running": "An index sync is already running.",
    "migration_busy": "Startup migration is still running.",
    "model_unavailable": "The local model runtime is not ready.",
    "desktop_unavailable": "Desktop is not ready to start a library sync.",
    "desktop_timeout": "Desktop did not accept the sync in time.",
    "failed": "Failed to start library sync.",
}


class AgentIndexSyncRejected(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = str(code)
        self.message = str(message)


def register_agent_index_sync_handler(handler: Handler) -> None:
    global _handler
    with _lock:
        _handler = handler


def unregister_agent_index_sync_handler(handler: Handler) -> None:
    global _handler
    with _lock:
        if _handler is handler:
            _handler = None


def register_agent_add_library_handler(handler: AddHandler) -> None:
    global _add_handler
    with _lock:
        _add_handler = handler


def unregister_agent_add_library_handler(handler: AddHandler) -> None:
    global _add_handler
    with _lock:
        if _add_handler is handler:
            _add_handler = None


def agent_index_sync_available() -> bool:
    with _lock:
        return (
            _handler is not None
            and _add_handler is not None
            and _refresh_handler is not None
            and _include_handler is not None
        )


def register_agent_library_refresh_handler(handler: Handler) -> None:
    global _refresh_handler
    with _lock:
        _refresh_handler = handler


def unregister_agent_library_refresh_handler(handler: Handler) -> None:
    global _refresh_handler
    with _lock:
        if _refresh_handler is handler:
            _refresh_handler = None


def request_agent_index_sync(
    library_paths: List[str],
    video_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    with _lock:
        handler = _handler
    if handler is None:
        return {"accepted": False, "reason": "desktop_unavailable"}
    result = handler(list(library_paths), None if video_ids is None else list(video_ids))
    return dict(result or {})


def request_agent_library_refresh(library_paths: List[str]) -> Dict[str, Any]:
    with _lock:
        handler = _refresh_handler
    if handler is None:
        return {"accepted": False, "reason": "desktop_unavailable"}
    result = handler(list(library_paths))
    return dict(result or {})


def register_agent_include_handler(handler: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
    global _include_handler
    with _lock:
        _include_handler = handler


def unregister_agent_include_handler(handler: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
    global _include_handler
    with _lock:
        if _include_handler is handler:
            _include_handler = None


def request_agent_include(plan: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        handler = _include_handler
    if handler is None:
        return {"accepted": False, "reason": "desktop_unavailable"}
    result = handler(dict(plan))
    return dict(result or {})


def request_agent_add_library(library_path: str) -> Dict[str, Any]:
    with _lock:
        handler = _add_handler
    if handler is None:
        return {"accepted": False, "reason": "desktop_unavailable"}
    result = handler(str(library_path or ""))
    return dict(result or {})


def _reject(reason: str) -> None:
    code = reason if reason in _STATUS else "failed"
    raise AgentIndexSyncRejected(_STATUS[code], code, _MESSAGES[code])


def resolve_sync_library_paths(library_path: Optional[str] = None) -> List[str]:
    from src.services.library_service import list_libraries
    from src.services.search_scope import normalize_scope_path

    libraries = list_libraries(maintain=False)
    keys = [str(key) for key in libraries.keys() if str(key or "").strip()]
    raw = str(library_path or "").strip()
    if not raw:
        if not keys:
            _reject("no_libraries")
        return keys
    target = normalize_scope_path(raw)
    for key in keys:
        if normalize_scope_path(key) == target:
            return [key]
    _reject("unknown_library")
    return []


def _catalog_videos() -> tuple[Dict[str, str], Dict[str, tuple[str, str]]]:
    import os

    from src.services.library_service import list_libraries
    from src.services.search_scope import normalize_scope_path

    by_id: Dict[str, str] = {}
    by_path: Dict[str, tuple[str, str]] = {}
    libraries = list_libraries(maintain=False)
    for lib, data in libraries.items():
        files = (data or {}).get("files") or {}
        if not isinstance(files, dict):
            continue
        for rel, info in files.items():
            if not isinstance(info, dict):
                continue
            vid = str(info.get("vid") or "").strip()
            rel_text = str(rel or "").strip()
            if not vid or not rel_text:
                continue
            abs_path = os.path.normpath(os.path.join(str(lib), rel_text))
            by_id[vid] = str(lib)
            by_path[normalize_scope_path(abs_path)] = (vid, str(lib))
    return by_id, by_path


def resolve_sync_selection(
    library_path: Optional[str] = None,
    video_ids: Optional[List[str]] = None,
    video_paths: Optional[List[str]] = None,
) -> tuple[Optional[List[str]], List[str]]:
    """Return ``(video ids or None, library paths)``. None ids means the whole library."""
    from src.services.search_scope import normalize_scope_path

    ids_in = [str(item).strip() for item in (video_ids or []) if str(item or "").strip()]
    paths_in = [str(item).strip() for item in (video_paths or []) if str(item or "").strip()]
    asked = video_ids is not None or video_paths is not None
    if asked and not ids_in and not paths_in:
        _reject("video_selection_empty")
    if not ids_in and not paths_in:
        return None, resolve_sync_library_paths(library_path)
    if len(ids_in) + len(paths_in) > _MAX_SYNC_VIDEOS:
        _reject("too_many_videos")

    by_id, by_path = _catalog_videos()
    scope = ""
    scope_key = ""
    if str(library_path or "").strip():
        scope = resolve_sync_library_paths(library_path)[0]
        scope_key = normalize_scope_path(scope)

    chosen: List[str] = []
    libs: List[str] = []
    seen: set[str] = set()

    def take(vid: str, lib: str) -> None:
        if scope and normalize_scope_path(lib) != scope_key:
            _reject("video_outside_library")
        if vid in seen:
            return
        seen.add(vid)
        chosen.append(vid)
        if lib not in libs:
            libs.append(lib)

    for vid in ids_in:
        lib = by_id.get(vid)
        if not lib:
            _reject("unknown_video")
        take(vid, lib)
    for path in paths_in:
        hit = by_path.get(normalize_scope_path(path))
        if not hit:
            _reject("unknown_video")
        take(hit[0], hit[1])
    return chosen, libs


def execute_agent_index_sync(
    library_path: Optional[str] = None,
    video_ids: Optional[List[str]] = None,
    video_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    from src.services.indexing_runtime_status import get_index_sync_status
    from src.services.team_mode_service import is_team_client_mode

    if is_team_client_mode():
        _reject("team_client")
    selected, paths = resolve_sync_selection(library_path, video_ids, video_paths)
    result = request_agent_index_sync(paths, video_ids=selected)
    if not result.get("accepted"):
        _reject(str(result.get("reason") or "failed"))
    accepted_paths = result.get("library_paths") or paths
    payload: Dict[str, Any] = {
        "api_version": API_VERSION,
        "ok": True,
        "accepted": True,
        "reason": "started",
        "library_paths": [str(path) for path in accepted_paths],
        **get_index_sync_status(),
    }
    if selected is not None:
        payload["video_ids"] = list(selected)
    return payload


def execute_agent_library_refresh(library_path: Optional[str] = None) -> Dict[str, Any]:
    from src.services.indexing_runtime_status import get_index_sync_status
    from src.services.team_mode_service import is_team_client_mode

    if is_team_client_mode():
        _reject("team_client")
    paths = resolve_sync_library_paths(library_path)
    result = request_agent_library_refresh(paths)
    if not result.get("accepted"):
        _reject(str(result.get("reason") or "failed"))
    accepted_paths = result.get("library_paths") or paths
    return {
        "api_version": API_VERSION,
        "ok": True,
        "accepted": True,
        "reason": "started",
        "library_paths": [str(path) for path in accepted_paths],
        **get_index_sync_status(),
    }


def _require_new_library_folder(library_path: Optional[str]) -> str:
    import os

    raw = str(library_path or "").strip().strip('"')
    if not raw:
        _reject("library_path_required")
    if not os.path.isabs(raw) or not os.path.isdir(raw):
        _reject("invalid_library_path")
    return raw


def execute_agent_add_library(library_path: Optional[str] = None) -> Dict[str, Any]:
    from src.services.indexing_runtime_status import get_index_sync_status
    from src.services.team_mode_service import is_team_client_mode

    if is_team_client_mode():
        _reject("team_client")
    folder = _require_new_library_folder(library_path)
    result = request_agent_add_library(folder)
    if not result.get("accepted"):
        reason = str(result.get("reason") or "failed")
        if reason == "exists":
            _reject("library_exists")
        if reason == "overlap":
            conflict = str(result.get("conflict_path") or "").strip()
            message = _MESSAGES["library_overlap"]
            if conflict:
                message = f"That folder overlaps {conflict}."
            raise AgentIndexSyncRejected(409, "library_overlap", message)
        _reject(reason)
    path = str(result.get("library_path") or folder)
    return {
        "api_version": API_VERSION,
        "ok": True,
        "accepted": True,
        "added": True,
        "reason": "started",
        "library_path": path,
        **get_index_sync_status(),
    }


def _norm_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(str(path or "")))


def _directory_contains(directory: str, path: str) -> bool:
    parent = _norm_path(directory)
    child = _norm_path(path)
    if not parent or not child or parent == child:
        return False
    try:
        return os.path.commonpath([parent, child]) == parent
    except ValueError:
        return False


def _video_suffix_ok(path: str) -> bool:
    from src.media.formats import VIDEO_EXTS

    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def _overlap_conflict(folder: str, libraries: List[str]) -> str:
    from src.services.library_service import _paths_overlap

    for existing in libraries:
        if _paths_overlap(folder, existing):
            return existing
    return ""


def plan_include_videos(video_paths: Optional[List[str]]) -> Dict[str, Any]:
    """Classify user video files. Register whole folders; index only the named files."""
    incoming = [str(item or "").strip().strip('"') for item in (video_paths or [])]
    incoming = [item for item in incoming if item]
    if not incoming:
        _reject("video_selection_empty")
    if len(incoming) > _MAX_SYNC_VIDEOS:
        _reject("too_many_videos")

    from src.services.library_service import list_libraries
    from src.services.search_scope import normalize_scope_path

    libraries = [str(key) for key in list_libraries(maintain=False).keys() if str(key or "").strip()]
    by_id, by_path = _catalog_videos()
    del by_id

    accepted: List[Dict[str, str]] = []
    rejected: List[Dict[str, str]] = []
    outside: List[str] = []

    for raw in incoming:
        if not os.path.isabs(raw) or not os.path.isfile(raw) or not _video_suffix_ok(raw):
            rejected.append({"video_path": raw, "reason": "invalid_video_path"})
            continue
        abs_path = os.path.normpath(raw)
        owners = [lib for lib in libraries if _directory_contains(lib, abs_path)]
        owners.sort(key=lambda item: len(_norm_path(item)), reverse=True)
        if owners:
            known = by_path.get(normalize_scope_path(abs_path))
            accepted.append(
                {
                    "video_path": abs_path,
                    "library_path": owners[0],
                    "action": "index" if known else "refresh",
                    "video_id": known[0] if known else "",
                }
            )
            continue
        outside.append(abs_path)

    grouped: Dict[str, List[str]] = {}
    for abs_path in outside:
        grouped.setdefault(os.path.normpath(os.path.dirname(abs_path)), []).append(abs_path)
    outer_for: Dict[str, str] = {}
    for parent in grouped:
        container = parent
        for other in grouped:
            if other != parent and _directory_contains(other, parent) and len(_norm_path(other)) < len(_norm_path(container)):
                container = other
        outer_for[parent] = container
    folded: Dict[str, List[str]] = {}
    for parent, files in grouped.items():
        folded.setdefault(outer_for[parent], []).extend(files)

    libraries_to_add: List[str] = []
    for parent, files in folded.items():
        conflict = _overlap_conflict(parent, libraries)
        if conflict:
            for file_path in files:
                rejected.append(
                    {
                        "video_path": file_path,
                        "reason": "library_overlap",
                        "conflict_path": conflict,
                    }
                )
            continue
        libraries_to_add.append(parent)
        for file_path in files:
            accepted.append(
                {
                    "video_path": file_path,
                    "library_path": parent,
                    "action": "add",
                    "video_id": "",
                }
            )

    register: List[str] = []
    for item in accepted:
        if item["action"] in {"refresh", "add"} and item["library_path"] not in register:
            register.append(item["library_path"])
    return {
        "accepted_videos": accepted,
        "rejected": rejected,
        "libraries_to_add": libraries_to_add,
        "libraries_to_register": register,
        "video_paths": [item["video_path"] for item in accepted],
    }


def execute_agent_include_videos(video_paths: Optional[List[str]] = None) -> Dict[str, Any]:
    from src.services.indexing_runtime_status import get_index_sync_status
    from src.services.team_mode_service import is_team_client_mode

    if is_team_client_mode():
        _reject("team_client")
    plan = plan_include_videos(video_paths)
    if not plan["video_paths"]:
        return {
            "api_version": API_VERSION,
            "ok": True,
            "accepted": False,
            "reason": "rejected",
            "rejected": plan["rejected"],
            "video_paths": [],
            "library_paths": [],
            **get_index_sync_status(),
        }
    result = request_agent_include(plan)
    if not result.get("accepted"):
        reason = str(result.get("reason") or "failed")
        if reason == "rejected":
            return {
                "api_version": API_VERSION,
                "ok": True,
                "accepted": False,
                "reason": "rejected",
                "rejected": result.get("rejected") or plan["rejected"],
                "video_paths": [],
                "library_paths": [],
                **get_index_sync_status(),
            }
        _reject(reason)
    return {
        "api_version": API_VERSION,
        "ok": True,
        "accepted": True,
        "reason": "started",
        "video_paths": list(result.get("video_paths") or plan["video_paths"]),
        "library_paths": list(result.get("library_paths") or plan["libraries_to_register"]),
        "libraries_added": list(result.get("libraries_added") or plan["libraries_to_add"]),
        "rejected": list(result.get("rejected") or plan["rejected"]),
        **get_index_sync_status(),
    }
