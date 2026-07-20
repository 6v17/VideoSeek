import logging
import os
import time
from logging.handlers import RotatingFileHandler


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOGGER_NAME = "videoseek"
# Size-rotated app.log (+ a few backups). Cap keeps disk/IO impact tiny.
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3
# Also drop any leftover files in the logs folder older than this.
LOG_RETENTION_DAYS = 7


def get_app_data_dir():
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return os.path.join(local_appdata, "VideoSeek")
    return os.path.join(os.path.expanduser("~"), ".videoseek")


def get_log_dir() -> str:
    return os.path.join(get_app_data_dir(), "logs")


def get_log_file():
    return os.path.join(get_log_dir(), "app.log")


def cleanup_old_logs(
    log_dir: str | None = None,
    *,
    retention_days: int = LOG_RETENTION_DAYS,
    now: float | None = None,
) -> int:
    """Delete log files in ``log_dir`` older than ``retention_days``. Returns removed count."""
    root = str(log_dir or get_log_dir() or "").strip()
    if not root or not os.path.isdir(root):
        return 0
    days = max(1, int(retention_days or LOG_RETENTION_DAYS))
    cutoff = float(now if now is not None else time.time()) - (days * 24 * 3600)
    removed = 0
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    for name in names:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        lower = name.lower()
        if not (lower.endswith(".log") or ".log." in lower):
            continue
        try:
            if os.path.getmtime(path) >= cutoff:
                continue
            os.remove(path)
            removed += 1
        except OSError:
            continue
    return removed


def silence_native_media_logs() -> None:
    """Quiet OpenCV / libavcodec chatter (e.g. h264 'Missing reference picture')."""
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    # FFmpeg AV_LOG_ERROR = 16; some OpenCV builds also honor OPENCV_FFMPEG_LOGLEVEL.
    os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "16")
    os.environ.setdefault("AV_LOG_FORCE_NOCOLOR", "1")
    try:
        import cv2

        level = getattr(cv2, "LOG_LEVEL_ERROR", None)
        if level is None:
            level = 3
        if hasattr(cv2, "setLogLevel"):
            cv2.setLogLevel(int(level))
    except Exception:
        pass


def setup_logging(level=logging.INFO):
    silence_native_media_logs()
    root_logger = logging.getLogger(LOGGER_NAME)
    if root_logger.handlers:
        root_logger.setLevel(level)
        return root_logger

    root_logger.setLevel(level)
    root_logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    log_file = get_log_file()
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    cleanup_old_logs(os.path.dirname(log_file), retention_days=LOG_RETENTION_DAYS)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name):
    base_logger = logging.getLogger(LOGGER_NAME)
    if not base_logger.handlers:
        setup_logging()
    return base_logger.getChild(name)
