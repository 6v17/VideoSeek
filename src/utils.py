import gc
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

import cv2
import numpy as np

from src.app.logging_utils import get_logger

logger = get_logger("utils")

#
def measure_time(message=""):
    def decorator(func):
        def wrapper(*args, **kwargs):
            started = time.time()
            result = func(*args, **kwargs)
            logger.info("%s %s took %.2fs", message, func.__name__, time.time() - started)
            return result

        return wrapper

    return decorator


def get_ffmpeg_path():
    resolved_path, _ = resolve_ffmpeg_path_info()
    return resolved_path or "ffmpeg"


def get_app_data_dir():
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return os.path.join(local_appdata, "VideoSeek")
    return os.path.join(os.path.expanduser("~"), ".videoseek")


def get_default_model_dir():
    return os.path.join(get_app_data_dir(), "models")


def get_default_ffmpeg_path():
    return os.path.join(get_app_data_dir(), "bin", "ffmpeg.exe")


def get_configured_ffmpeg_target_path(config=None):
    from src.app.config import load_config

    current_config = dict(config or load_config())
    configured_path = str(current_config.get("ffmpeg_path", "") or "").strip()
    if configured_path:
        normalized_path = os.path.normpath(configured_path)
        if os.path.isabs(normalized_path) or os.path.dirname(normalized_path):
            return normalized_path
    return os.path.normpath(get_default_ffmpeg_path())


def has_ffmpeg():
    ffmpeg_path = get_ffmpeg_path()
    return os.path.exists(ffmpeg_path) or shutil.which(ffmpeg_path) is not None


def get_ffmpeg_status_text():
    resolved_path, source = resolve_ffmpeg_path_info()
    if source == "system":
        return f"PATH: {resolved_path}"
    return resolved_path or "Unavailable"


def resolve_ffmpeg_path_info():
    from src.app.config import load_config

    config = load_config()
    configured_path = get_configured_ffmpeg_target_path(config)
    if configured_path and os.path.exists(configured_path):
        return configured_path, "configured"

    default_path = get_default_ffmpeg_path()
    if os.path.exists(default_path):
        return default_path, "managed"

    if getattr(sys, "frozen", False) or "__file__" not in globals():
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.abspath(".")

    bundled_path = os.path.join(base_dir, "ffmpeg.exe")
    if os.path.exists(bundled_path):
        return bundled_path, "bundled"

    system_path = shutil.which("ffmpeg")
    if system_path:
        return system_path, "system"

    return "", "missing"


def sync_ffmpeg_path_to_config():
    from src.app.config import load_config, save_config

    config = load_config()
    configured_path = str(config.get("ffmpeg_path", "") or "").strip()
    if configured_path:
        normalized_path = os.path.normpath(configured_path)
        if normalized_path != configured_path:
            config["ffmpeg_path"] = normalized_path
            save_config(config)
        return normalized_path

    resolved_path, source = resolve_ffmpeg_path_info()
    if source == "missing" or not resolved_path:
        return ""

    config["ffmpeg_path"] = resolved_path
    save_config(config)
    return resolved_path


def resolve_model_dir_info():
    try:
        from src.app.config import load_config

        configured_model_dir = str(load_config().get("model_dir", "") or "").strip()
        if configured_model_dir:
            return os.path.normpath(configured_model_dir), "configured"
    except Exception:
        pass

    return os.path.normpath(get_default_model_dir()), "default"


def sync_model_dir_to_config():
    from src.app.config import load_config, save_config

    config = load_config()
    configured_model_dir = str(config.get("model_dir", "") or "").strip()
    if configured_model_dir:
        normalized_dir = os.path.normpath(configured_model_dir)
        if normalized_dir != configured_model_dir:
            config["model_dir"] = normalized_dir
            save_config(config)
        return normalized_dir

    resolved_dir, _ = resolve_model_dir_info()
    if not resolved_dir:
        return ""

    config["model_dir"] = resolved_dir
    save_config(config)
    return resolved_dir


def get_configured_model_dir():
    resolved_dir, _ = resolve_model_dir_info()
    return resolved_dir


def resolve_resource_path(relative_path, configured_base_dir=""):
    normalized_relative = relative_path.replace("/", os.sep)
    candidate_paths = []

    if configured_base_dir:
        configured_name = os.path.basename(normalized_relative)
        candidate_paths.append(os.path.join(configured_base_dir, configured_name))

    candidate_paths.append(get_resource_path(normalized_relative))

    for candidate in candidate_paths:
        if os.path.exists(candidate):
            return candidate

    return candidate_paths[0]


def get_model_path(filename):
    return resolve_resource_path(os.path.join("models", filename), get_configured_model_dir())


def get_missing_model_files(model_filenames):
    missing = []
    resolved_paths = {}

    for filename in model_filenames:
        path = get_model_path(filename)
        resolved_paths[filename] = path
        if not os.path.exists(path):
            missing.append(filename)

    return missing, resolved_paths


def ensure_model_files(model_filenames):
    missing, resolved_paths = get_missing_model_files(model_filenames)

    if missing:
        missing_display = ", ".join(missing)
        raise FileNotFoundError(
            f"Missing model files: {missing_display}. "
            f"Place them in '{get_configured_model_dir()}' or next to the app under 'models'."
        )

    return resolved_paths


def free_memory():
    gc.collect()
    logger.info("Memory cleanup completed")


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


def create_preview_clip(input_path, start_sec, output_path, duration_sec=None):
    from src.app.config import load_config

    ffmpeg = get_ffmpeg_path()
    config = load_config()
    preview_seconds = float(config.get("preview_seconds", 6))
    preview_width = config.get("preview_width", 640)
    preview_height = config.get("preview_height", 360)

    input_path = os.fspath(input_path)
    output_path = os.fspath(output_path)
    start_sec = max(0.0, float(start_sec))
    clip_duration = preview_seconds if duration_sec is None else max(0.1, float(duration_sec))

    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    fast_seek = max(0.0, start_sec - 1.0)
    precise_seek = start_sec - fast_seek

    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        f"{fast_seek:.3f}",
        "-i",
        input_path,
        "-ss",
        f"{precise_seek:.3f}",
        "-t",
        f"{clip_duration:.3f}",
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
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        output_path,
    ]

    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    return subprocess.run(cmd, startupinfo=startupinfo, capture_output=True)


def export_original_clip(input_path, start_sec, duration_sec, output_path):
    cmd = build_export_original_clip_command(input_path, start_sec, duration_sec, output_path)
    return subprocess.run(cmd, startupinfo=_build_hidden_startupinfo(), capture_output=True)


def start_export_original_clip_process(input_path, start_sec, duration_sec, output_path):
    cmd = build_export_original_clip_command(input_path, start_sec, duration_sec, output_path)
    return subprocess.Popen(
        cmd,
        startupinfo=_build_hidden_startupinfo(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def build_export_original_clip_command(input_path, start_sec, duration_sec, output_path):
    ffmpeg = get_ffmpeg_path()
    input_path = os.fspath(input_path)
    output_path = os.fspath(output_path)
    start_sec = max(0.0, float(start_sec))
    duration_sec = max(0.1, float(duration_sec))

    ensure_folder_exists(output_path)
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    return [
        ffmpeg,
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-i",
        input_path,
        "-t",
        f"{duration_sec:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        output_path,
    ]


def _build_hidden_startupinfo():
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    return startupinfo


def get_video_duration_seconds(video_path):
    stream_info = get_video_stream_info(video_path)
    duration = stream_info.get("duration")
    if duration is not None and duration > 0:
        return duration
    return _probe_video_duration_with_opencv(video_path)


def get_video_stream_info(video_path):
    ffprobe_path = get_ffprobe_path()
    if not ffprobe_path:
        return {"width": None, "height": None, "duration": None}

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:format=duration",
        "-of",
        "json",
        os.fspath(video_path),
    ]

    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            startupinfo=startupinfo,
            timeout=10,
        )
        if result.returncode != 0:
            return {"width": None, "height": None, "duration": None}

        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams") or []
        stream = streams[0] if streams else {}
        format_payload = payload.get("format") or {}
        return {
            "width": _safe_int(stream.get("width")),
            "height": _safe_int(stream.get("height")),
            "duration": _safe_float(format_payload.get("duration")),
        }
    except Exception:
        return {"width": None, "height": None, "duration": None}


def has_readable_video_stream(video_path):
    stream_info = get_video_stream_info(video_path)
    if stream_info.get("width") and stream_info.get("height"):
        return True

    fallback_info = _probe_video_stream_with_opencv(video_path)
    return bool(fallback_info.get("width") and fallback_info.get("height"))


def get_ffprobe_path():
    ffmpeg_path = get_ffmpeg_path()
    ffmpeg_dir = os.path.dirname(ffmpeg_path)
    ffmpeg_name = os.path.basename(ffmpeg_path).lower()
    if ffmpeg_name.startswith("ffmpeg"):
        candidate_name = ffmpeg_name.replace("ffmpeg", "ffprobe", 1)
        candidate_path = os.path.join(ffmpeg_dir, candidate_name)
        if os.path.exists(candidate_path):
            return candidate_path
    return shutil.which("ffprobe") or ""


def _probe_video_duration_with_opencv(video_path):
    return _probe_video_stream_with_opencv(video_path).get("duration")


def _probe_video_stream_with_opencv(video_path):
    path = os.fspath(video_path)
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        capture.release()
        return {"width": None, "height": None, "duration": None}

    width = float(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0.0)
    height = float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0.0)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    capture.release()

    duration = None
    if fps > 0.0 and frame_count > 0.0:
        duration = frame_count / fps

    return {
        "width": int(width) if width > 0.0 else None,
        "height": int(height) if height > 0.0 else None,
        "duration": duration,
    }


def _safe_float(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _safe_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_duration_token(token):
    text = str(token or "").strip().lower()
    if not text:
        return None
    multiplier = 1.0
    if text.endswith("ms"):
        multiplier = 0.001
        text = text[:-2]
    elif text.endswith("s"):
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 60.0
        text = text[:-1]
    elif text.endswith("h"):
        multiplier = 3600.0
        text = text[:-1]
    value = float(text)
    return max(0.0, value * multiplier)


def _has_explicit_duration_unit(token):
    text = str(token or "").strip().lower()
    if not text:
        return False
    if text == "0":
        return True
    return text.endswith("m")


def normalize_sampling_fps_rules_text(rules_text):
    text = str(rules_text or "")
    text = text.replace("\uFF1B", ";").replace("\uFF0C", ";").replace("\r", "\n")
    parts = []
    for chunk in text.replace("\n", ";").split(";"):
        item = chunk.strip()
        if item:
            parts.append(item)
    return "; ".join(parts)


def normalize_sampling_fps_mode(mode):
    normalized = str(mode or "").strip().lower()
    if normalized in {"dynamic", "rules", "mapping", "duration_map", "adaptive", "auto"}:
        return "dynamic"
    return "fixed"


def _parse_sampling_rule_item(item, index):
    if "=" not in item or "-" not in item:
        raise ValueError(f"Rule {index + 1} must use start-end=fps format")

    range_part, fps_part = item.split("=", 1)
    start_text, end_text = range_part.split("-", 1)
    start_text = start_text.strip()
    end_text = end_text.strip()
    if start_text and not _has_explicit_duration_unit(start_text):
        raise ValueError(f"Rule {index + 1} start duration must include a unit")
    if end_text and not _has_explicit_duration_unit(end_text):
        raise ValueError(f"Rule {index + 1} end duration must include a unit")
    min_duration = _parse_duration_token(start_text) if start_text.strip() else 0.0
    max_duration = _parse_duration_token(end_text) if end_text.strip() else None
    fps_value = float(fps_part.strip())
    if fps_value < 0.01:
        raise ValueError(f"Rule {index + 1} fps must be at least 0.01")
    if max_duration is not None and max_duration < min_duration:
        raise ValueError(f"Rule {index + 1} end duration must be greater than start duration")
    return {
        "min_duration": float(min_duration),
        "max_duration": None if max_duration is None else float(max_duration),
        "fps": float(fps_value),
        "index": index,
    }


def validate_sampling_fps_rules(rules_text):
    normalized_text = normalize_sampling_fps_rules_text(rules_text)
    if not normalized_text:
        return True, ""

    parsed_rules = []
    for index, chunk in enumerate(normalized_text.split(";")):
        item = chunk.strip()
        if not item:
            continue
        try:
            parsed_rules.append(_parse_sampling_rule_item(item, index))
        except (TypeError, ValueError):
            return False, f"Rule {index + 1}"

    sorted_rules = sorted(
        parsed_rules,
        key=lambda rule: (rule["min_duration"], float("inf") if rule["max_duration"] is None else rule["max_duration"]),
    )
    previous_rule = None
    for rule in sorted_rules:
        if previous_rule is None:
            previous_rule = rule
            continue
        previous_max = previous_rule["max_duration"]
        if previous_max is None or rule["min_duration"] < previous_max:
            return False, f"Rule {rule['index'] + 1}"
        previous_rule = rule
    return True, ""


def parse_sampling_fps_rules(rules_text):
    rules = []
    normalized_text = normalize_sampling_fps_rules_text(rules_text)
    for index, chunk in enumerate(normalized_text.split(";")):
        item = chunk.strip()
        if not item:
            continue
        try:
            rules.append(_parse_sampling_rule_item(item, index))
        except (TypeError, ValueError):
            continue
    return rules


def _match_sampling_rule(duration_sec, rules):
    matched_rule = None
    matched_width = None
    for rule in rules:
        min_duration = float(rule["min_duration"])
        max_duration = rule["max_duration"]
        if duration_sec < min_duration:
            continue
        if max_duration is not None and duration_sec >= float(max_duration):
            continue
        width = float("inf") if max_duration is None else float(max_duration) - min_duration
        if matched_rule is None or width < matched_width or (width == matched_width and rule["index"] > matched_rule["index"]):
            matched_rule = rule
            matched_width = width
    return matched_rule


def resolve_sampling_fps(duration_sec=None, config=None, requested_fps=None):
    from src.app.config import load_config

    config = dict(config or load_config())
    base_fps = float(requested_fps) if requested_fps is not None else float(config.get("fps", 1.0))
    base_fps = max(0.01, base_fps)
    if normalize_sampling_fps_mode(config.get("sampling_fps_mode", "fixed")) != "dynamic":
        return base_fps

    try:
        duration_value = float(duration_sec)
    except (TypeError, ValueError):
        return base_fps
    if duration_value <= 0:
        return base_fps
    rules = parse_sampling_fps_rules(config.get("sampling_fps_rules", ""))
    matched_rule = _match_sampling_rule(duration_value, rules)
    if matched_rule is not None:
        return float(matched_rule["fps"])
    return base_fps


def build_preview_cache_path(video_path, start_sec):
    from src.app.config import get_data_storage_paths

    cache_dir = get_data_storage_paths().get("preview_cache_dir", "")
    if not cache_dir:
        cache_dir = os.path.join(get_app_data_dir(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    key = f"{video_path}|{int(start_sec)}|{uuid.uuid4().hex}"
    filename = f"preview_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}.mp4"
    return os.path.join(cache_dir, filename)


def libx264_param():
    # Retained intentionally until ffmpeg codec selection is fully inlined.
    return "libx264"


def open_in_explorer(video_path):
    path = os.fspath(video_path)
    if not os.path.exists(path):
        logger.warning("File does not exist: %s", video_path)
        return False

    path = os.path.normpath(os.path.abspath(path))

    if sys.platform == "win32":
        try:
            subprocess.run(["explorer", "/select,", path], check=False)
        except Exception as exc:
            logger.warning("Windows locate failed: %s", exc)
            os.startfile(os.path.dirname(path))
    elif sys.platform == "darwin":
        subprocess.run(["open", "-R", path], check=False)
    else:
        subprocess.run(["xdg-open", os.path.dirname(path)], check=False)
    return True


def open_folder_in_explorer(folder_path):
    if not os.path.exists(folder_path):
        logger.warning("Folder does not exist: %s", folder_path)
        return

    path = os.path.normpath(os.path.abspath(folder_path))

    if sys.platform == "win32":
        try:
            os.startfile(path)
        except OSError as exc:
            logger.warning("Windows folder open failed: %s", exc)
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


def get_single_thumbnail(video_path, time_sec):
    # Retained intentionally: imported dynamically inside ThumbLoader.run().
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
        logger.warning("Thumbnail capture failed: %s", exc)
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
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    return os.path.join(base_path, relative_path)
