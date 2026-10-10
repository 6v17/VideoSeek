"""Shared FFmpeg clip export (Agent API + desktop shot list)."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Sequence

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.services.search_scope import normalize_scope_path, video_path_under_library_root
from src.utils import (
    EXPORT_ENCODE_MODE_COPY,
    export_original_clip,
    get_ffmpeg_path,
    normalize_export_encode_mode,
    resolve_export_clip_window,
)

logger = get_logger("clip_export_service")


def last_export_dir(config=None) -> str:
    """Last folder used by desktop clip export, if it still exists."""
    cfg = config if isinstance(config, dict) else load_config()
    path = str(cfg.get("export_last_dir") or "").strip()
    if path and os.path.isdir(path):
        return os.path.normpath(path)
    return ""


def remember_export_path(path: str) -> None:
    """Persist the folder of a chosen export file or directory."""
    raw = str(path or "").strip()
    if not raw:
        return
    folder = raw if os.path.isdir(raw) else os.path.dirname(raw)
    if not folder or not os.path.isdir(folder):
        return
    normalized = os.path.normpath(folder)
    from src.app.config import save_config

    cfg = load_config()
    if os.path.normpath(str(cfg.get("export_last_dir") or "")) == normalized:
        return
    cfg["export_last_dir"] = normalized
    save_config(cfg)


def export_save_dialog_start(filename: str, config=None) -> str:
    """Suggested save path: last export folder plus the file name."""
    name = os.path.basename(str(filename or "").strip()) or "clip.mp4"
    folder = last_export_dir(config)
    if folder:
        return os.path.join(folder, name)
    return name


EXPORT_CLIP_TIMEOUT_SEC = 120.0
BATCH_EXPORT_TIMEOUT_MIN_SEC = 120.0
BATCH_EXPORT_TIMEOUT_MAX_SEC = 900.0
MAX_BATCH_EXPORT_CLIPS = 64
MAX_BATCH_EXPORT_WORKERS = 8
MAX_CONCURRENT_ORIGINAL_EXPORTS = 1
MAX_CONCURRENT_COPY_EXPORTS = 3

_original_export_semaphore = threading.Semaphore(MAX_CONCURRENT_ORIGINAL_EXPORTS)
_copy_export_semaphore = threading.Semaphore(MAX_CONCURRENT_COPY_EXPORTS)


def resolve_clip_window(
    video_path: str,
    start_sec: float,
    end_sec: Optional[float] = None,
    config=None,
    encode_mode: Optional[str] = None,
) -> tuple[float, float]:
    """Return (clip_start, clip_duration) — same rules as desktop preview export."""
    cfg = config or load_config()
    mode = normalize_export_encode_mode(
        encode_mode if encode_mode is not None else EXPORT_ENCODE_MODE_COPY
    )
    return resolve_export_clip_window(
        video_path,
        start_sec,
        end_sec=end_sec,
        encode_mode=mode,
        config=cfg,
    )


def default_agent_export_root() -> str:
    """Fallback export directory under app data (team / strict agent writes)."""
    from src.app.logging_utils import get_app_data_dir

    return os.path.normpath(os.path.join(get_app_data_dir(), "exports"))


def export_path_guard_strict(config=None) -> bool:
    """When True, Agent/team exports must land under ``list_export_allowed_roots``."""
    forced = str(os.environ.get("VIDEOSEEK_AGENT_EXPORT_STRICT", "") or "").strip().lower()
    if forced in {"1", "true", "yes", "on"}:
        return True
    if forced in {"0", "false", "no", "off"}:
        return False
    cfg = config or load_config()
    try:
        from src.services.team_mode_service import is_team_server_mode

        if is_team_server_mode(cfg):
            return True
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "src/services/clip_export_service.py:export_path_guard_strict")
    return False


def list_export_allowed_roots(config=None) -> list[str]:
    """Absolute normalized roots where Agent/team export writes are allowed."""
    cfg = config or load_config()
    roots: list[str] = []

    def _add(raw: str) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        roots.append(normalize_scope_path(os.path.abspath(os.path.expanduser(text))))

    configured = cfg.get("agent_export_allowed_roots", [])
    if isinstance(configured, str):
        for part in configured.replace(";", os.pathsep).split(os.pathsep):
            _add(part)
    elif isinstance(configured, (list, tuple)):
        for item in configured:
            _add(str(item or ""))

    env = str(os.environ.get("VIDEOSEEK_AGENT_EXPORT_ROOTS", "") or "").strip()
    if env:
        for part in env.replace(";", os.pathsep).split(os.pathsep):
            _add(part)

    if export_path_guard_strict(cfg) or roots:
        _add(default_agent_export_root())

    seen: set[str] = set()
    ordered: list[str] = []
    for root in roots:
        if not root or root in seen:
            continue
        seen.add(root)
        ordered.append(root)
    return ordered


def _resolve_export_path(path: str) -> str:
    """Absolute path with symlinks and Windows junctions resolved.

    A missing final file name stays on the resolved parent, so a new export
    still follows a link in its directory. ``os.path.islink`` is not enough
    here: it does not see junctions.
    """
    expanded = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not expanded:
        return ""
    try:
        resolved = os.path.realpath(expanded)
    except (OSError, ValueError):
        resolved = expanded
    if resolved.startswith("\\\\?\\UNC\\"):
        resolved = "\\\\" + resolved[8:]
    elif resolved.startswith("\\\\?\\"):
        resolved = resolved[4:]
    return os.path.normcase(os.path.normpath(resolved or expanded))


def _export_path_roots(*raw_roots: str) -> list[str]:
    roots: list[str] = []
    for raw in raw_roots:
        text = str(raw or "").strip()
        if not text:
            continue
        lexical = normalize_scope_path(text)
        resolved = _resolve_export_path(text)
        for candidate in (lexical, resolved):
            if candidate and candidate not in roots:
                roots.append(candidate)
    return roots


def output_path_allowed(output_path: str, config=None) -> bool:
    """Reject library overwrites; in team/strict mode require an allowed export root.

    The path that would be written is the symlink/junction target, not only the
    lexical path. A link that points into a library is rejected. A link that
    leaves an allowed export root is rejected too.
    """
    from src.services.library_service import list_libraries

    cfg = config or load_config()
    lexical = normalize_scope_path(output_path)
    resolved = _resolve_export_path(output_path)
    library_roots = _export_path_roots(*(str(path) for path in list_libraries().keys()))
    for candidate in (lexical, resolved):
        if candidate and any(video_path_under_library_root(candidate, root) for root in library_roots):
            return False

    roots = list_export_allowed_roots(cfg)
    if not roots and not export_path_guard_strict(cfg):
        # Localhost Agent: historical contract — any path outside libraries.
        return True
    if not roots:
        return False
    allowed = _export_path_roots(*roots)
    landing = resolved or lexical
    return bool(landing) and any(video_path_under_library_root(landing, root) for root in allowed)


def _export_semaphore_for_mode(encode_mode: str) -> threading.Semaphore:
    if encode_mode == EXPORT_ENCODE_MODE_COPY:
        return _copy_export_semaphore
    return _original_export_semaphore


def _meta_encode_mode_label(encode_mode: str) -> str:
    if encode_mode == EXPORT_ENCODE_MODE_COPY:
        return "stream_copy"
    return "libx264_crf18"


def execute_export_clip(
    *,
    video_path: str,
    start_sec: float,
    end_sec: float,
    output_path: str,
    client_request_id: Optional[str] = None,
    silent: Optional[bool] = None,
    encode_mode: Optional[str] = None,
    config=None,
) -> Dict[str, Any]:
    cfg = config or load_config()
    encode_mode = normalize_export_encode_mode(
        encode_mode if encode_mode is not None else EXPORT_ENCODE_MODE_COPY
    )
    source = os.path.normpath(os.path.abspath(os.path.expanduser(str(video_path or "").strip())))
    if not source or not os.path.isfile(source):
        raise FileNotFoundError(f"video_path does not exist: {video_path}")

    destination = os.path.normpath(os.path.abspath(os.path.expanduser(str(output_path or "").strip())))
    if not destination:
        raise ValueError("output_path is required.")
    if not destination.lower().endswith((".mp4", ".mkv", ".mov")):
        raise ValueError("output_path must end with .mp4, .mkv, or .mov")
    if not output_path_allowed(destination, config=cfg):
        raise ValueError("output_path must not be inside an indexed library root.")

    start = float(start_sec)
    end = float(end_sec)
    effective_end = end if end > start + 1e-3 else None

    clip_start, clip_duration = resolve_clip_window(
        source,
        start,
        end_sec=effective_end,
        config=cfg,
        encode_mode=encode_mode,
    )
    clip_end = clip_start + clip_duration
    use_silent = bool(cfg.get("export_video_silent", False)) if silent is None else bool(silent)

    from src.utils import has_ffmpeg

    if not has_ffmpeg():
        raise RuntimeError("FFmpeg is not available. Install or configure FFmpeg in VideoSeek settings.")

    started = time.perf_counter()
    semaphore = _export_semaphore_for_mode(encode_mode)
    acquired = semaphore.acquire(timeout=EXPORT_CLIP_TIMEOUT_SEC)
    if not acquired:
        raise RuntimeError("Clip export queue is busy. Retry shortly.")
    try:
        result = export_original_clip(
            source,
            clip_start,
            clip_duration,
            destination,
            silent=use_silent,
            encode_mode=encode_mode,
        )
    finally:
        semaphore.release()

    if result.returncode != 0:
        stderr = ""
        try:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        except Exception as exc:
            from src.app.logging_utils import note_swallowed

            note_swallowed(exc, "src/services/clip_export_service.py:ffmpeg_stderr")
            stderr = ""
        message = stderr or f"FFmpeg exited with code {result.returncode}"
        raise RuntimeError(message[:2000])

    payload: Dict[str, Any] = {
        "api_version": "1",
        "ok": True,
        "output_path": destination,
        "video_path": source,
        "start_sec": clip_start,
        "end_sec": clip_end,
        "duration_sec": clip_duration,
        "encode_mode": encode_mode,
        "ffmpeg_path": get_ffmpeg_path(),
        "meta": {
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "encode_mode": _meta_encode_mode_label(encode_mode),
            "silent": use_silent,
        },
    }
    if client_request_id:
        payload["client_request_id"] = str(client_request_id)
    return payload


def _batch_export_item_error(
    *,
    video_path: str = "",
    output_path: str = "",
    client_request_id: Optional[str] = None,
    code: str,
    message: str,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "ok": False,
        "video_path": str(video_path or ""),
        "output_path": str(output_path or ""),
        "error": {"code": code, "message": message},
    }
    if client_request_id:
        entry["client_request_id"] = str(client_request_id)
    return entry


def _batch_export_item_encode_mode(item, default_encode_mode: str) -> str:
    raw = getattr(item, "encode_mode", None)
    if raw is not None and str(raw).strip():
        return normalize_export_encode_mode(raw)
    return normalize_export_encode_mode(default_encode_mode)


def resolve_batch_export_timeout_sec(item_count: int, encode_mode: str) -> float:
    count = max(1, int(item_count))
    per_item = EXPORT_CLIP_TIMEOUT_SEC
    mode = normalize_export_encode_mode(encode_mode)
    if mode == EXPORT_ENCODE_MODE_COPY:
        lanes = max(1, MAX_CONCURRENT_COPY_EXPORTS)
        estimated = (count / float(lanes)) * per_item + 15.0
    else:
        estimated = count * per_item + 15.0
    return min(BATCH_EXPORT_TIMEOUT_MAX_SEC, max(BATCH_EXPORT_TIMEOUT_MIN_SEC, estimated * 1.05))


def _run_batch_export_item(
    item,
    *,
    default_encode_mode: str,
    default_silent: Optional[bool],
    config,
) -> Dict[str, Any]:
    video_path = str(getattr(item, "video_path", "") or "").strip()
    output_path = str(getattr(item, "output_path", "") or "").strip()
    client_request_id = getattr(item, "client_request_id", None)
    silent = getattr(item, "silent", None)
    if silent is None:
        silent = default_silent
    try:
        payload = execute_export_clip(
            video_path=video_path,
            start_sec=float(getattr(item, "start_sec")),
            end_sec=float(getattr(item, "end_sec")),
            output_path=output_path,
            client_request_id=client_request_id,
            silent=silent,
            encode_mode=_batch_export_item_encode_mode(item, default_encode_mode),
            config=config,
        )
        payload["ok"] = True
        return payload
    except FileNotFoundError as exc:
        return _batch_export_item_error(
            video_path=video_path,
            output_path=output_path,
            client_request_id=client_request_id,
            code="invalid_request",
            message=str(exc),
        )
    except ValueError as exc:
        return _batch_export_item_error(
            video_path=video_path,
            output_path=output_path,
            client_request_id=client_request_id,
            code="invalid_request",
            message=str(exc),
        )
    except RuntimeError as exc:
        message = str(exc)
        code = "engine_busy" if "queue is busy" in message.lower() else "export_failed"
        return _batch_export_item_error(
            video_path=video_path,
            output_path=output_path,
            client_request_id=client_request_id,
            code=code,
            message=message,
        )
    except Exception as exc:
        return _batch_export_item_error(
            video_path=video_path,
            output_path=output_path,
            client_request_id=client_request_id,
            code="export_failed",
            message=str(exc),
        )


def execute_batch_export_clips(body) -> Dict[str, Any]:
    """Export multiple clips (parallel when continue_on_error)."""
    items: Sequence = list(getattr(body, "items", None) or [])
    if not items:
        raise ValueError("Provide at least one entry in items.")
    if len(items) > MAX_BATCH_EXPORT_CLIPS:
        raise ValueError(f"Batch size exceeds limit ({MAX_BATCH_EXPORT_CLIPS}).")

    cfg = load_config()
    default_encode_mode = normalize_export_encode_mode(
        getattr(body, "encode_mode", None) or EXPORT_ENCODE_MODE_COPY
    )
    default_silent = getattr(body, "silent", None)
    continue_on_error = bool(getattr(body, "continue_on_error", True))

    from src.utils import has_ffmpeg

    if not has_ffmpeg():
        raise RuntimeError("FFmpeg is not available. Install or configure FFmpeg in VideoSeek settings.")

    started = time.perf_counter()
    results: List[Dict[str, Any]] = []

    if continue_on_error:
        ordered: List[Optional[Dict[str, Any]]] = [None] * len(items)
        workers = min(MAX_BATCH_EXPORT_WORKERS, len(items))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _run_batch_export_item,
                    item,
                    default_encode_mode=default_encode_mode,
                    default_silent=default_silent,
                    config=cfg,
                ): index
                for index, item in enumerate(items)
            }
            for future in as_completed(futures):
                index = futures[future]
                ordered[index] = future.result()
        results = [entry for entry in ordered if entry is not None]
    else:
        for item in items:
            entry = _run_batch_export_item(
                item,
                default_encode_mode=default_encode_mode,
                default_silent=default_silent,
                config=cfg,
            )
            results.append(entry)
            if not entry.get("ok"):
                break

    succeeded = sum(1 for entry in results if entry.get("ok"))
    failed = len(results) - succeeded

    batch_timeout_sec = resolve_batch_export_timeout_sec(len(items), default_encode_mode)
    return {
        "api_version": "1",
        "ok": failed == 0,
        "results": results,
        "meta": {
            "total": len(items),
            "processed": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "continue_on_error": continue_on_error,
            "encode_mode_default": default_encode_mode,
            "batch_timeout_sec": int(batch_timeout_sec),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "max_batch_export_clips": MAX_BATCH_EXPORT_CLIPS,
        },
    }
