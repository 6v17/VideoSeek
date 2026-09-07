"""Single-frame extract for Agent API (JPEG base64)."""

from __future__ import annotations

import base64
import os
import time
from typing import Any, Dict, List, Optional

from .constants import API_VERSION
from .schemas import AgentBatchFrameExtractRequest, AgentFrameExtractRequest

DEFAULT_FRAME_MAX_EDGE = 1280
_MIN_FRAME_MAX_EDGE = 64
_MAX_FRAME_MAX_EDGE = 1920
_JPEG_QUALITY = 85
MAX_BATCH_FRAME_EXTRACT = 16


def _normalize_video_path(video_path: str) -> str:
    source = os.path.normpath(os.path.abspath(os.path.expanduser(str(video_path or "").strip())))
    if not source or not os.path.isfile(source):
        raise FileNotFoundError(f"video_path does not exist: {video_path}")
    return source


def _clamp_max_edge(max_edge: Optional[int]) -> int:
    if max_edge is None:
        return DEFAULT_FRAME_MAX_EDGE
    try:
        value = int(max_edge)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_edge must be an integer") from exc
    return max(_MIN_FRAME_MAX_EDGE, min(_MAX_FRAME_MAX_EDGE, value))


def _resize_bgr(frame, max_edge: int):
    import cv2

    height, width = int(frame.shape[0]), int(frame.shape[1])
    longest = max(height, width)
    if longest <= 0 or longest <= max_edge:
        return frame
    scale = float(max_edge) / float(longest)
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)


def execute_agent_frame_extract(body: AgentFrameExtractRequest) -> Dict[str, Any]:
    started = time.perf_counter()
    source = _normalize_video_path(body.video_path)
    try:
        time_sec = max(0.0, float(body.time_sec))
    except (TypeError, ValueError) as exc:
        raise ValueError("time_sec must be a number") from exc
    max_edge = _clamp_max_edge(body.max_edge)

    from src.media.thumbnail import get_single_thumbnail

    frame = get_single_thumbnail(source, time_sec)
    if frame is None or getattr(frame, "size", 0) == 0:
        raise RuntimeError(f"failed to extract frame at {time_sec:.3f}s from {source}")

    frame = _resize_bgr(frame, max_edge)
    import cv2

    ok, buffer = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY],
    )
    if not ok or buffer is None:
        raise RuntimeError("failed to encode JPEG frame")

    height, width = int(frame.shape[0]), int(frame.shape[1])
    image_b64 = base64.b64encode(buffer.tobytes()).decode("ascii")
    return {
        "api_version": API_VERSION,
        "ok": True,
        "video_path": source,
        "time_sec": time_sec,
        "width": width,
        "height": height,
        "mime": "image/jpeg",
        "image_base64": image_b64,
        "client_request_id": body.client_request_id,
        "meta": {
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "max_edge": max_edge,
        },
    }


def execute_agent_batch_frame_extract(body: AgentBatchFrameExtractRequest) -> Dict[str, Any]:
    started = time.perf_counter()
    items = list(body.items or [])
    if not items:
        raise ValueError("items must not be empty.")
    if len(items) > MAX_BATCH_FRAME_EXTRACT:
        raise ValueError(f"Batch frame extract exceeds limit ({MAX_BATCH_FRAME_EXTRACT}).")

    batch_max_edge = body.max_edge
    continue_on_error = bool(body.continue_on_error)
    results: List[Dict[str, Any]] = []
    succeeded = 0
    failed = 0

    for item in items:
        effective = item
        if item.max_edge is None and batch_max_edge is not None:
            effective = AgentFrameExtractRequest(
                video_path=item.video_path,
                time_sec=item.time_sec,
                max_edge=batch_max_edge,
                client_request_id=item.client_request_id,
            )
        try:
            payload = execute_agent_frame_extract(effective)
            results.append(payload)
            succeeded += 1
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            failed += 1
            code = "invalid_request"
            if isinstance(exc, FileNotFoundError):
                code = "not_found"
            elif isinstance(exc, RuntimeError):
                code = "frame_extract_failed"
            results.append(
                {
                    "ok": False,
                    "video_path": str(item.video_path or ""),
                    "time_sec": item.time_sec,
                    "client_request_id": item.client_request_id,
                    "error": {"code": code, "message": str(exc)},
                }
            )
            if not continue_on_error:
                break
        except Exception as exc:
            failed += 1
            results.append(
                {
                    "ok": False,
                    "video_path": str(item.video_path or ""),
                    "time_sec": item.time_sec,
                    "client_request_id": item.client_request_id,
                    "error": {"code": "frame_extract_failed", "message": str(exc)},
                }
            )
            if not continue_on_error:
                break

    return {
        "api_version": API_VERSION,
        "ok": failed == 0,
        "results": results,
        "meta": {
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "total": len(items),
            "succeeded": succeeded,
            "failed": failed,
            "continue_on_error": continue_on_error,
            "max_batch_frame_extract": MAX_BATCH_FRAME_EXTRACT,
            "max_edge": _clamp_max_edge(batch_max_edge) if batch_max_edge is not None else None,
        },
    }
