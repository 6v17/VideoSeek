import gc
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid

import cv2
import numpy as np


def measure_time(message=""):
    def decorator(func):
        def wrapper(*args, **kwargs):
            started = time.time()
            result = func(*args, **kwargs)
            print(f"{message} {func.__name__} took: {time.time() - started:.2f}s")
            return result

        return wrapper

    return decorator


def get_ffmpeg_path():
    from src.app.config import load_config

    config = load_config()
    configured_path = config.get("ffmpeg_path", "").strip()
    if configured_path:
        return configured_path

    if getattr(sys, "frozen", False) or "__file__" not in globals():
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.abspath(".")

    ffmpeg_exe = os.path.join(base_dir, "ffmpeg.exe")
    if not os.path.exists(ffmpeg_exe):
        ffmpeg_exe = "ffmpeg"
    return ffmpeg_exe


def free_memory():
    gc.collect()
    print("Memory cleanup completed.")


def ensure_folder_exists(file_path):
    folder = os.path.dirname(file_path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)


def canonicalize_library_path(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def get_video_hash(video_path):
    digest = hashlib.sha256()
    with open(video_path, "rb") as handle:
        digest.update(handle.read(10 * 1024 * 1024))
    return digest.hexdigest()


def save_meta(meta, meta_file):
    ensure_folder_exists(meta_file)
    with open(meta_file, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=4, ensure_ascii=False)


def create_preview_clip(input_path, start_sec, output_path):
    from src.app.config import load_config

    ffmpeg = get_ffmpeg_path()
    config = load_config()
    preview_seconds = config.get("preview_seconds", 6)
    preview_width = config.get("preview_width", 640)
    preview_height = config.get("preview_height", 360)

    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        str(max(0, start_sec - 1)),
        "-t",
        str(preview_seconds),
        "-i",
        input_path,
        "-s",
        f"{preview_width}x{preview_height}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-crf",
        "32",
        "-an",
        output_path,
    ]

    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    return subprocess.run(cmd, startupinfo=startupinfo, capture_output=True)


def build_preview_cache_path(video_path, start_sec):
    cache_dir = os.path.join(os.environ["LOCALAPPDATA"], "VideoSeek", "cache")
    os.makedirs(cache_dir, exist_ok=True)
    key = f"{video_path}|{int(start_sec)}|{uuid.uuid4().hex}"
    filename = f"preview_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}.mp4"
    return os.path.join(cache_dir, filename)


def libx264_param():
    return "libx264"


def open_in_explorer(video_path):
    if not os.path.exists(video_path):
        print(f"File does not exist: {video_path}")
        return

    path = os.path.normpath(os.path.abspath(video_path))

    if sys.platform == "win32":
        try:
            subprocess.run(["explorer", f"/select,{path}"], check=False)
        except Exception as exc:
            print(f"Windows locate failed: {exc}")
            os.startfile(os.path.dirname(path))
    elif sys.platform == "darwin":
        subprocess.run(["open", "-R", path], check=False)
    else:
        subprocess.run(["xdg-open", os.path.dirname(path)], check=False)


def open_folder_in_explorer(folder_path):
    if not os.path.exists(folder_path):
        print(f"Folder does not exist: {folder_path}")
        return

    path = os.path.normpath(os.path.abspath(folder_path))

    if sys.platform == "win32":
        try:
            os.startfile(path)
        except OSError as exc:
            print(f"Windows folder open failed: {exc}")
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


def get_single_thumbnail(video_path, time_sec):
    ffmpeg_bin = get_ffmpeg_path()
    cmd = [
        ffmpeg_bin,
        "-ss",
        str(time_sec),
        "-i",
        video_path,
        "-vframes",
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
        print(f"Thumbnail capture failed: {exc}")
    return None


def load_meta(meta_file):
    if not os.path.exists(meta_file):
        return {"libraries": {}}

    try:
        with open(meta_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise RuntimeError(f"Failed to load metadata file: {meta_file}") from exc

    if "libraries" not in data:
        data["libraries"] = {}
    return data


def get_resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)

    if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)
