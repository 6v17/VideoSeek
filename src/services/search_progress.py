from __future__ import annotations

import threading
from typing import Callable

ProgressCallback = Callable[[str, str], None]

_progress_local = threading.local()


def set_search_progress_callback(callback: ProgressCallback | None) -> None:
    _progress_local.callback = callback


def get_search_progress_callback() -> ProgressCallback | None:
    callback = getattr(_progress_local, "callback", None)
    return callback if callable(callback) else None


def clear_search_progress_callback() -> None:
    if hasattr(_progress_local, "callback"):
        delattr(_progress_local, "callback")


def emit_search_progress(phase: str, message: str = "") -> None:
    callback = get_search_progress_callback()
    if callback is None:
        return
    try:
        callback(str(phase or "").strip(), str(message or "").strip())
    except Exception:
        pass
