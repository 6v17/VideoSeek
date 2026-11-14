"""Plain-text error report a user can paste back to identify a failure."""

from __future__ import annotations

import os
import platform
import sys
import traceback
from datetime import datetime


def build_error_report(
    operation: str,
    error: BaseException | str | None = None,
    *,
    language: str = "zh",
    page: str = "",
) -> str:
    """One block: what they did, the exception, the function, and recent logs."""
    zh = not str(language or "zh").lower().startswith("en")
    labels = _LABELS_ZH if zh else _LABELS_EN
    lines = [
        labels["title"],
        f"{labels['time']}: {_now()}",
        f"{labels['version']}: {_version()}",
        f"{labels['system']}: {_system()}",
        f"{labels['python']}: {platform.python_version()}",
        f"{labels['mode']}: {_run_mode(zh)}",
    ]
    page_name = str(page or "").strip()
    if page_name:
        lines.append(f"{labels['page']}: {page_name}")
    action = str(operation or "").strip() or "-"
    lines.append(f"{labels['operation']}: {action}")

    exc = error if isinstance(error, BaseException) else None
    message = _error_message(error)
    if exc is not None:
        lines.append(f"{labels['exception']}: {type(exc).__name__}")
    if message:
        lines.append(f"{labels['message']}: {message}")

    tb = _traceback_for(exc)
    frames = traceback.extract_tb(tb) if tb is not None else []
    if frames:
        last = frames[-1]
        lines.append(f"{labels['function']}: {_short_path(last.filename)}:{last.lineno} {last.name}()")
        rendered = "".join(traceback.format_exception(type(exc), exc, tb)).strip()
        lines.append(labels["traceback"] + ":")
        lines.append(_clip(rendered, 6000))
    else:
        caller = _caller_frames()
        if caller:
            last = caller[-1]
            lines.append(f"{labels['function']}: {_short_path(last.filename)}:{last.lineno} {last.name}()")
            lines.append(labels["call_stack"] + ":")
            lines.extend(
                f"  {_short_path(frame.filename)}:{frame.lineno} {frame.name}()"
                for frame in caller[-12:]
            )

    logs = _recent_logs()
    if logs:
        lines.append(labels["logs"] + ":")
        lines.append(logs)
    return "\n".join(lines).strip() + "\n"


_LABELS_ZH = {
    "title": "VideoSeek 错误报告",
    "time": "时间",
    "version": "版本",
    "system": "系统",
    "python": "Python",
    "mode": "模式",
    "page": "页面",
    "operation": "操作",
    "exception": "异常",
    "message": "信息",
    "function": "函数",
    "traceback": "堆栈",
    "call_stack": "调用",
    "logs": "最近日志",
}

_LABELS_EN = {
    "title": "VideoSeek error report",
    "time": "Time",
    "version": "Version",
    "system": "System",
    "python": "Python",
    "mode": "Mode",
    "page": "Page",
    "operation": "Operation",
    "exception": "Exception",
    "message": "Message",
    "function": "Function",
    "traceback": "Traceback",
    "call_stack": "Call stack",
    "logs": "Recent logs",
}

_SKIP_FILES = ("error_report.py", "app_message.py", "error_hook.py")


def _now() -> str:
    try:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "-"


def _version() -> str:
    try:
        from src.app.config import get_app_version

        return str(get_app_version() or "-")
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "error_report.version")
        return "-"


def _system() -> str:
    try:
        return platform.platform()
    except Exception:
        return sys.platform


def _run_mode(zh: bool) -> str:
    client = "用户机" if zh else "user machine"
    server = "服务机" if zh else "server machine"
    local = "本机" if zh else "this machine"
    try:
        from src.services.team_mode_service import is_team_client_mode, is_team_server_mode

        if is_team_client_mode():
            return client
        if is_team_server_mode():
            return server
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "error_report.run_mode")
    return local


def _error_message(error: BaseException | str | None) -> str:
    if error is None:
        return ""
    text = str(error).strip()
    if len(text) > 1500:
        return text[:1500] + "…"
    return text


def _traceback_for(error: BaseException | None):
    if error is None:
        return None
    if error.__traceback__ is not None:
        return error.__traceback__
    _etype, value, tb = sys.exc_info()
    if value is error:
        return tb
    return None


def _caller_frames() -> list[traceback.FrameSummary]:
    frames = traceback.extract_stack()[:-1]
    kept = []
    for frame in frames:
        if os.path.basename(frame.filename) in _SKIP_FILES:
            continue
        if frame.name in {"show_error_dialog", "_current_nav_page_id", "present_error_dialog"}:
            continue
        kept.append(frame)
    return kept


def _short_path(path: str) -> str:
    text = str(path or "").replace("\\", "/")
    lowered = text.lower()
    for marker in ("/src/", "/ui/", "/tests/"):
        index = lowered.rfind(marker)
        if index >= 0:
            return text[index + 1 :]
    return os.path.basename(text) or text


def _clip(text: str, limit: int) -> str:
    body = str(text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit] + "…"


def _recent_logs() -> str:
    try:
        from src.app.logging_utils import recent_log_lines

        return "\n".join(recent_log_lines(25))
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "error_report.logs")
        return ""
