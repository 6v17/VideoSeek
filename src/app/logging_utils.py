import logging
import os
import time
import zipfile
from collections import deque
from logging.handlers import RotatingFileHandler
from threading import Lock


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


def _is_log_filename(name: str) -> bool:
    lower = str(name or "").lower()
    return lower.endswith(".log") or ".log." in lower


def flush_app_logs() -> None:
    """Push buffered lines to disk before a user exports the log folder."""
    root_logger = logging.getLogger(LOGGER_NAME)
    for handler in list(root_logger.handlers):
        try:
            handler.flush()
        except Exception as exc:
            note_swallowed(exc, "logging_utils.flush_app_logs")


def export_logs_zip(dest_path: str, log_dir: str | None = None) -> int:
    """Pack app.log and its rotated backups into a zip. Returns how many files were written."""
    root = str(log_dir or get_log_dir() or "").strip()
    dest = str(dest_path or "").strip()
    if not dest:
        raise ValueError("missing destination")
    if log_dir is None:
        flush_app_logs()
    names = []
    if root and os.path.isdir(root):
        try:
            names = sorted(name for name in os.listdir(root) if _is_log_filename(name))
        except OSError:
            names = []
    files = [os.path.join(root, name) for name in names if os.path.isfile(os.path.join(root, name))]
    if not files:
        raise FileNotFoundError("no log files")
    parent = os.path.dirname(os.path.abspath(dest))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=os.path.basename(path))
    return len(files)


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
    """Quiet OpenCV / libavcodec chatter (e.g. h264 'Missing reference picture').

    Env vars only at startup — avoid importing cv2 before the UI window appears.
    ``apply_opencv_log_level()`` can refine after OpenCV is first loaded.
    """
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    # FFmpeg AV_LOG_ERROR = 16; some OpenCV builds also honor OPENCV_FFMPEG_LOGLEVEL.
    os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "16")
    os.environ.setdefault("AV_LOG_FORCE_NOCOLOR", "1")


def apply_opencv_log_level() -> None:
    """Best-effort OpenCV log level after cv2 is already imported elsewhere."""
    try:
        import cv2

        level = getattr(cv2, "LOG_LEVEL_ERROR", None)
        if level is None:
            level = 3
        if hasattr(cv2, "setLogLevel"):
            cv2.setLogLevel(int(level))
    except Exception:
        pass


class RecentLogHandler(logging.Handler):
    """Keep the last few formatted lines so an error dialog can copy them."""

    def __init__(self, capacity: int = 40):
        super().__init__(level=logging.INFO)
        self._lines: deque[str] = deque(maxlen=max(1, int(capacity)))
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            return
        if len(line) > 400:
            line = line[:400] + "…"
        with self._lock:
            self._lines.append(line)

    def snapshot(self, limit: int = 30) -> list[str]:
        with self._lock:
            lines = list(self._lines)
        count = max(0, int(limit))
        if count and len(lines) > count:
            return lines[-count:]
        return lines


_RECENT_LOGS: RecentLogHandler | None = None


def recent_log_handler() -> RecentLogHandler:
    global _RECENT_LOGS
    if _RECENT_LOGS is None:
        _RECENT_LOGS = RecentLogHandler()
        _RECENT_LOGS.setFormatter(logging.Formatter(LOG_FORMAT))
    return _RECENT_LOGS


def recent_log_lines(limit: int = 30) -> list[str]:
    return recent_log_handler().snapshot(limit)


def setup_logging(level=logging.INFO):
    silence_native_media_logs()
    root_logger = logging.getLogger(LOGGER_NAME)
    if root_logger.handlers:
        root_logger.setLevel(level)
        recent = recent_log_handler()
        if recent not in root_logger.handlers:
            root_logger.addHandler(recent)
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

    recent = recent_log_handler()
    recent.setFormatter(formatter)
    if recent not in root_logger.handlers:
        root_logger.addHandler(recent)

    return root_logger


def get_logger(name):
    base_logger = logging.getLogger(LOGGER_NAME)
    if not base_logger.handlers:
        setup_logging()
    return base_logger.getChild(name)


def note_swallowed(exc: BaseException, where: str = "") -> None:
    """Record a caught failure that still returns an empty sentinel.

    Callers keep their fallback value; the log is what makes the failure visible.
    """
    try:
        get_logger("swallowed").warning("%s: %s", where or "except", exc)
    except Exception:
        pass
