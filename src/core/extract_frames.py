import subprocess

import numpy as np

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.utils import get_ffmpeg_path, get_video_duration_seconds, resolve_sampling_fps

logger = get_logger("extract_frames")


def extract_frames_with_ffmpeg(video_path):
    config = load_config()
    video_duration = get_video_duration_seconds(video_path)
    fps = resolve_sampling_fps(video_duration, config=config)

    ffmpeg_bin = get_ffmpeg_path()
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        video_path,
        "-vf",
        f"fps={fps:.6f},scale=224:224",
        "-sn",
        "-f",
        "image2pipe",
        "-pix_fmt",
        "bgr24",
        "-vcodec",
        "rawvideo",
        "-",
    ]

    frames = []
    timestamps = []
    frame_size = 224 * 224 * 3
    count = 0

    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    process = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
        )

        while True:
            if not process.stdout:
                break
            in_bytes = process.stdout.read(frame_size)
            if len(in_bytes) != frame_size:
                break

            frame = np.frombuffer(in_bytes, np.uint8).reshape((224, 224, 3))
            frames.append(frame)
            timestamps.append(count / fps)
            count += 1

        return_code = process.wait(timeout=20)
        stderr_text = ""
        if process.stderr:
            stderr_text = process.stderr.read().decode("utf-8", errors="replace").strip()
        if return_code != 0:
            logger.error("FFmpeg frame extraction failed for %s with code %s: %s", video_path, return_code, stderr_text)
            return [], []
        if not frames:
            logger.warning("FFmpeg produced no frames for %s at %.3f FPS", video_path, fps)
            if stderr_text:
                logger.warning("FFmpeg stderr for %s: %s", video_path, stderr_text)
            return [], []

        logger.info("Frame extraction completed: %s frames for %s at %.3f FPS", len(frames), video_path, fps)
        return frames, timestamps
    except Exception as exc:
        logger.error("Frame extraction crashed for %s: %s", video_path, exc)
        return [], []
    finally:
        if process is not None:
            try:
                if process.stdout:
                    process.stdout.close()
            except Exception:
                pass
            try:
                if process.stderr:
                    process.stderr.close()
            except Exception:
                pass
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
            except Exception:
                pass
