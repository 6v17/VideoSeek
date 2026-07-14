"""Single-frame thumbnail capture (OpenCV + ffmpeg fallback)."""

from __future__ import annotations

import os
import subprocess
import sys

import cv2
import numpy as np

from src.app.logging_utils import get_logger
from src.infra.ffmpeg_paths import get_ffmpeg_path

logger = get_logger("thumbnail")


def get_single_thumbnail(video_path, time_sec):
    # Retained intentionally: imported dynamically inside ThumbLoader.run().
    path = str(video_path or "").strip()
    if not path or not os.path.isfile(path):
        return None
    safe_time = max(0.0, float(time_sec))
    # Fast path: keep one lightweight local decoder process.
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

    # Fallback path: ffmpeg hybrid seek when OpenCV decode fails.
    ffmpeg_bin = get_ffmpeg_path()
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
            timeout=3,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        buffer = np.frombuffer(process.stdout, np.uint8)
        if len(buffer) > 0:
            return cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.warning("Thumbnail capture failed: %s", exc)
    return None
