"""Single-frame thumbnail capture (OpenCV + ffmpeg fallback)."""

from __future__ import annotations

import os
import subprocess
import sys

import numpy as np

from src.app.logging_utils import get_logger
from src.infra.ffmpeg_paths import get_ffmpeg_path

logger = get_logger("thumbnail")


def _cv2():
    import cv2
    from src.app.logging_utils import apply_opencv_log_level

    apply_opencv_log_level()
    return cv2


def _is_http_media_url(path: str) -> bool:
    text = str(path or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _ffmpeg_capture_frame(video_path: str, time_sec: float, *, timeout_sec: float = 3.0):
    ffmpeg_bin = get_ffmpeg_path()
    safe_time = max(0.0, float(time_sec))
    preroll_sec = 0.35
    coarse_seek = max(0.0, safe_time - preroll_sec)
    fine_seek = safe_time - coarse_seek
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{coarse_seek:.3f}",
        "-i",
        video_path,
        "-ss",
        f"{fine_seek:.3f}",
        "-frames:v",
        "1",
        "-f",
        "image2",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    try:
        process = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            timeout=max(1.0, float(timeout_sec)),
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        buffer = np.frombuffer(process.stdout, np.uint8)
        if len(buffer) > 0:
            cv2 = _cv2()
            return cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.warning("Thumbnail capture failed: %s", exc)
    return None


def get_single_thumbnail(video_path, time_sec):
    # Retained intentionally: imported dynamically inside ThumbLoader.run().
    path = str(video_path or "").strip()
    if not path:
        return None
    http = _is_http_media_url(path)
    if not http and not os.path.isfile(path):
        return None
    safe_time = max(0.0, float(time_sec))

    # Remote team play URLs: ffmpeg handles HTTP range seeks more reliably than OpenCV.
    if http:
        return _ffmpeg_capture_frame(path, safe_time, timeout_sec=8.0)

    # Fast path: keep one lightweight local decoder process.
    cv2 = _cv2()
    capture = cv2.VideoCapture(path)
    try:
        if capture.isOpened():
            capture.set(cv2.CAP_PROP_POS_MSEC, safe_time * 1000.0)
            ok, frame = capture.read()
            if ok and frame is not None and frame.size > 0:
                return frame
    except Exception:
        pass
    finally:
        capture.release()

    return _ffmpeg_capture_frame(path, safe_time, timeout_sec=3.0)


def draw_top_caption_bar(frame_bgr, text: str, *, bar_height: int = 28):
    """Dark bar + ASCII caption. OpenCV Hershey cannot render CJK reliably."""
    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return frame_bgr
    label = str(text or "").strip()
    if not label:
        return frame_bgr
    cv2 = _cv2()
    height, width = int(frame_bgr.shape[0]), int(frame_bgr.shape[1])
    bar_h = max(18, min(int(bar_height), max(18, height // 5)))
    canvas = np.zeros((height + bar_h, width, 3), dtype=frame_bgr.dtype)
    canvas[bar_h:, :, :] = frame_bgr
    canvas[:bar_h, :, :] = (32, 32, 32)
    scale = 0.42 if width >= 160 else 0.36
    cv2.putText(
        canvas,
        label[:48],
        (6, bar_h - 8),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (240, 240, 240),
        1,
        cv2.LINE_AA,
    )
    return canvas


def compose_side_by_side_bgr(left_bgr, right_bgr, *, left_caption: str = "", right_caption: str = ""):
    """Resize to a shared height and concatenate left|right. Missing side is skipped."""
    frames = [frame for frame in (left_bgr, right_bgr) if frame is not None and getattr(frame, "size", 0)]
    captions = []
    if left_bgr is not None and getattr(left_bgr, "size", 0):
        captions.append(str(left_caption or ""))
    if right_bgr is not None and getattr(right_bgr, "size", 0) and len(frames) > 1:
        captions.append(str(right_caption or ""))
    if not frames:
        return None
    if len(frames) == 1:
        caption = captions[0] if captions else str(left_caption or right_caption or "")
        return draw_top_caption_bar(frames[0], caption) if caption else frames[0]
    cv2 = _cv2()
    left, right = frames[0], frames[1]
    height = min(int(left.shape[0]), int(right.shape[0]))
    if height <= 0:
        return left

    def _resize(frame):
        if int(frame.shape[0]) == height:
            return frame
        width = max(1, int(round(frame.shape[1] * (height / float(frame.shape[0])))))
        return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)

    left_r = _resize(left)
    right_r = _resize(right)
    if captions:
        left_r = draw_top_caption_bar(left_r, captions[0] if len(captions) > 0 else "")
        right_r = draw_top_caption_bar(right_r, captions[1] if len(captions) > 1 else "")
    return cv2.hconcat([left_r, right_r])
