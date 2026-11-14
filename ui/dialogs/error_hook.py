"""Show a copyable report when a slot or worker thread raises and nobody catches it."""

from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from src.app.logging_utils import get_logger
from ui.dialogs.app_message import present_error_dialog

logger = get_logger("error_hook")

_INSTALLED = False
_SHOWING = False


class _ErrorBridge(QObject):
    present = Signal(str, object)


def install_uncaught_exception_hook() -> None:
    """Replace sys.excepthook and threading.excepthook. Safe to call once after QApplication."""
    global _INSTALLED
    if _INSTALLED:
        return
    app = QApplication.instance()
    if app is None:
        return
    bridge = _ErrorBridge(app)
    bridge.present.connect(_present, Qt.ConnectionType.QueuedConnection)
    app._videoseek_error_bridge = bridge
    previous = sys.excepthook
    previous_thread = getattr(threading, "excepthook", None)

    def _hook(exc_type, exc, tb):
        if exc_type in (KeyboardInterrupt, SystemExit) or not isinstance(exc, BaseException):
            previous(exc_type, exc, tb)
            return
        try:
            logger.error("Uncaught %s: %s", getattr(exc_type, "__name__", exc_type), exc)
            bridge.present.emit(_uncaught_operation(_ui_language()), exc)
        except Exception:
            logger.exception("Failed to present an uncaught error")
            previous(exc_type, exc, tb)

    def _thread_hook(args):
        _hook(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = _hook
    if previous_thread is not None:
        threading.excepthook = _thread_hook
    _INSTALLED = True


def _present(operation: str, exc: object) -> None:
    global _SHOWING
    if _SHOWING:
        logger.error("Dropped a nested error dialog: %s", operation)
        return
    app = QApplication.instance()
    if app is None:
        return
    _SHOWING = True
    try:
        present_error_dialog(
            app.activeWindow(),
            operation,
            exc if isinstance(exc, BaseException) else str(exc or ""),
            language=_ui_language(),
        )
    except Exception:
        logger.exception("Error dialog failed")
    finally:
        _SHOWING = False


def _ui_language() -> str:
    try:
        from src.app.config import load_config

        lang = str(load_config().get("language") or "zh").strip().lower()
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "error_hook.language")
        lang = "zh"
    return "en" if lang.startswith("en") else "zh"


def _uncaught_operation(language: str) -> str:
    from src.app.i18n import get_texts

    return str(get_texts(language).get("error_uncaught") or "界面操作中断")


