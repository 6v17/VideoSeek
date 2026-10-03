"""Save one video frame at a timestamp as PNG or JPG."""

from __future__ import annotations

import os
import subprocess
import sys
import time

from src.app.logging_utils import get_logger
from src.infra.ffmpeg_paths import get_ffmpeg_path, has_ffmpeg

logger = get_logger("export_frame")

_STILL_EXTS = {".png", ".jpg", ".jpeg"}


def wait_for_written_file(path: str, timeout_sec: float = 2.0) -> bool:
    """Return once ``path`` exists and its size stops changing."""
    dest = str(path or "").strip()
    if not dest:
        return False
    deadline = time.monotonic() + max(0.1, float(timeout_sec))
    last_size = -1
    stable_reads = 0
    while time.monotonic() < deadline:
        if os.path.isfile(dest):
            try:
                size = os.path.getsize(dest)
            except OSError:
                size = 0
            if size > 0 and size == last_size:
                stable_reads += 1
                if stable_reads >= 2:
                    return True
            else:
                stable_reads = 0
            last_size = size
        time.sleep(0.04)
    try:
        return os.path.isfile(dest) and os.path.getsize(dest) > 0
    except OSError:
        return False


def publish_still(source_path: str, output_path: str) -> str:
    """Copy a captured PNG to ``output_path``, converting to JPG when asked."""
    source = os.path.abspath(str(source_path or "").strip())
    dest = os.path.abspath(str(output_path or "").strip())
    if not source or not dest:
        raise ValueError("missing path")
    ext = os.path.splitext(dest)[1].lower()
    if ext not in _STILL_EXTS:
        dest = dest + ".png"
        ext = ".png"
    folder = os.path.dirname(dest)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if ext in {".jpg", ".jpeg"}:
        from PIL import Image

        with Image.open(source) as image:
            image.convert("RGB").save(dest, quality=95)
    elif os.path.normcase(source) != os.path.normcase(dest):
        os.replace(source, dest)
    if os.path.normcase(source) != os.path.normcase(dest):
        try:
            os.remove(source)
        except OSError:
            pass
    if not os.path.isfile(dest) or os.path.getsize(dest) <= 0:
        raise RuntimeError("frame export failed")
    return dest


def save_video_frame(video_path: str, time_sec: float, output_path: str) -> str:
    """Write the frame at ``time_sec`` to ``output_path``. Returns the written path."""
    source = str(video_path or "").strip()
    dest = os.path.abspath(str(output_path or "").strip())
    if not source or not dest:
        raise ValueError("missing path")
    ext = os.path.splitext(dest)[1].lower()
    if ext not in _STILL_EXTS:
        dest = dest + ".png"
        ext = ".png"
    folder = os.path.dirname(dest)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if not has_ffmpeg():
        raise RuntimeError("ffmpeg missing")

    safe_time = max(0.0, float(time_sec))
    preroll_sec = 0.35
    coarse_seek = max(0.0, safe_time - preroll_sec)
    fine_seek = safe_time - coarse_seek
    cmd = [
        get_ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{coarse_seek:.3f}",
        "-i",
        source,
        "-ss",
        f"{fine_seek:.3f}",
        "-frames:v",
        "1",
    ]
    if ext == ".png":
        cmd.extend(["-c:v", "png"])
    else:
        cmd.extend(["-q:v", "2"])
    cmd.append(dest)
    try:
        subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            timeout=20,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
    except Exception as exc:
        logger.warning("Frame export failed: %s", exc)
        raise RuntimeError("frame export failed") from exc
    if not os.path.isfile(dest) or os.path.getsize(dest) <= 0:
        raise RuntimeError("frame export failed")
    return dest
