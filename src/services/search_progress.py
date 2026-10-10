from __future__ import annotations

import threading
from typing import Callable

ProgressCallback = Callable[[str, str], None]
StopCallback = Callable[[], bool]

_progress_local = threading.local()


def set_search_progress_callback(callback: ProgressCallback | None) -> None:
    _progress_local.callback = callback


def get_search_progress_callback() -> ProgressCallback | None:
    callback = getattr(_progress_local, "callback", None)
    return callback if callable(callback) else None


def clear_search_progress_callback() -> None:
    if hasattr(_progress_local, "callback"):
        delattr(_progress_local, "callback")


def set_search_stop_callback(callback: StopCallback | None) -> None:
    _progress_local.stop_callback = callback


def get_search_stop_callback() -> StopCallback | None:
    callback = getattr(_progress_local, "stop_callback", None)
    return callback if callable(callback) else None


def clear_search_stop_callback() -> None:
    if hasattr(_progress_local, "stop_callback"):
        delattr(_progress_local, "stop_callback")


def bind_search_callbacks(progress_callback, stop_callback):
    """Install callbacks for this search. ``None`` keeps the caller's callback.

    Nested ``run_search`` must not wipe the outer progress/stop hooks.
    """
    previous = (get_search_progress_callback(), get_search_stop_callback())
    if progress_callback is not None:
        set_search_progress_callback(progress_callback)
    if stop_callback is not None:
        set_search_stop_callback(stop_callback)
    return previous


def restore_search_callbacks(previous) -> None:
    progress_callback, stop_callback = previous
    set_search_progress_callback(progress_callback)
    set_search_stop_callback(stop_callback)


def search_should_stop() -> bool:
    callback = get_search_stop_callback()
    return bool(callback and callback())


def ensure_search_not_stopped() -> None:
    if search_should_stop():
        raise InterruptedError("search stopped")


def emit_search_progress(phase: str, message: str = "") -> None:
    ensure_search_not_stopped()
    callback = get_search_progress_callback()
    if callback is None:
        return
    try:
        callback(str(phase or "").strip(), str(message or "").strip())
    except InterruptedError:
        raise
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "src/services/search_progress.py:progress_callback")
