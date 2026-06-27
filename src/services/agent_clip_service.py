"""Agent API clip export (FFmpeg), shared with desktop preview export."""

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
    EXPORT_ENCODE_MODE_ORIGINAL,
    export_original_clip,
    get_ffmpeg_path,
    normalize_export_encode_mode,
    resolve_export_clip_window,
)

logger = get_logger("agent_clip_service")

_EXPORT_CLIP_TIMEOUT_SEC = 120.0
_BATCH_EXPORT_TIMEOUT_MIN_SEC = 120.0
_BATCH_EXPORT_TIMEOUT_MAX_SEC = 900.0
_MAX_BATCH_EXPORT_CLIPS = 64
_MAX_BATCH_EXPORT_WORKERS = 8
_MAX_CONCURRENT_ORIGINAL_EXPORTS = 1
_MAX_CONCURRENT_COPY_EXPORTS = 3
_original_export_semaphore = threading.Semaphore(_MAX_CONCURRENT_ORIGINAL_EXPORTS)
_copy_export_semaphore = threading.Semaphore(_MAX_CONCURRENT_COPY_EXPORTS)


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


def _output_path_allowed(output_path: str, config=None) -> bool:
    """Reject writes into indexed library roots (avoid overwriting source media)."""
    from src.services.library_service import list_libraries

    normalized_output = normalize_scope_path(output_path)
    for library_path in list_libraries().keys():
        if video_path_under_library_root(normalized_output, library_path):
            return False
    return True


def _export_semaphore_for_mode(encode_mode: str) -> threading.Semaphore:
    if encode_mode == EXPORT_ENCODE_MODE_COPY:
        return _copy_export_semaphore
    return _original_export_semaphore


def _meta_encode_mode_label(encode_mode: str) -> str:
    if encode_mode == EXPORT_ENCODE_MODE_COPY:
        return "stream_copy"
    return "libx264_crf18"


def execute_agent_export_clip(
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
    if not _output_path_allowed(destination, config=cfg):
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
    acquired = semaphore.acquire(timeout=_EXPORT_CLIP_TIMEOUT_SEC)
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
        except Exception:
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


def _resolve_batch_export_timeout_sec(item_count: int, encode_mode: str) -> float:
    count = max(1, int(item_count))
    per_item = _EXPORT_CLIP_TIMEOUT_SEC
    mode = normalize_export_encode_mode(encode_mode)
    if mode == EXPORT_ENCODE_MODE_COPY:
        lanes = max(1, _MAX_CONCURRENT_COPY_EXPORTS)
        estimated = (count / float(lanes)) * per_item + 15.0
    else:
        estimated = count * per_item + 15.0
    return min(_BATCH_EXPORT_TIMEOUT_MAX_SEC, max(_BATCH_EXPORT_TIMEOUT_MIN_SEC, estimated * 1.05))


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
        payload = execute_agent_export_clip(
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


def execute_agent_batch_export_clips(body) -> Dict[str, Any]:
    """Export multiple clips in one Agent API call (parallel when continue_on_error)."""
    items: Sequence = list(getattr(body, "items", None) or [])
    if not items:
        raise ValueError("Provide at least one entry in items.")
    if len(items) > _MAX_BATCH_EXPORT_CLIPS:
        raise ValueError(f"Batch size exceeds limit ({_MAX_BATCH_EXPORT_CLIPS}).")

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
        workers = min(_MAX_BATCH_EXPORT_WORKERS, len(items))
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

    batch_timeout_sec = _resolve_batch_export_timeout_sec(len(items), default_encode_mode)
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
            "max_batch_export_clips": _MAX_BATCH_EXPORT_CLIPS,
        },
    }
