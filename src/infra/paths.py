"""App install / data / resource path helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_app_data_dir():
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return os.path.join(local_appdata, "VideoSeek")
    return os.path.join(os.path.expanduser("~"), ".videoseek")


def get_default_model_dir():
    return os.path.join(get_app_data_dir(), "models")


def ensure_folder_exists(file_path):
    folder = os.path.dirname(file_path)
    if folder:
        os.makedirs(folder, exist_ok=True)


def resolve_windows_long_path(path: str) -> str:
    """Expand Windows 8.3 short paths (``D:\\VIDEOS~1`` → ``D:\\VideoSeek``).

    Packaged launches sometimes expose ``sys.executable`` as a short path. Python
    can often still open those paths, but Win nginx ``CreateFile`` fails with
    "The system cannot find the file specified" for ``nginx.conf``.
    """
    text = os.path.abspath(str(path or "").strip() or ".")
    if os.name != "nt":
        return text
    try:
        import ctypes

        get_long = ctypes.windll.kernel32.GetLongPathNameW  # type: ignore[attr-defined]
        needed = int(get_long(text, None, 0) or 0)
        if needed > 0:
            buffer = ctypes.create_unicode_buffer(needed)
            written = int(get_long(text, buffer, needed) or 0)
            if written > 0 and buffer.value:
                return buffer.value
    except Exception:
        pass
    try:
        return str(Path(text).resolve())
    except OSError:
        return text


def _windows_module_dir() -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        length = int(ctypes.windll.kernel32.GetModuleFileNameW(None, buffer, len(buffer)) or 0)
        if length <= 0:
            return ""
        return os.path.dirname(buffer.value[:length])
    except Exception:
        return ""


def _is_standalone_app() -> bool:
    """True for PyInstaller/Nuitka builds and other non-interpreter launches."""
    if getattr(sys, "frozen", False):
        return True
    # Nuitka sets __compiled__ on modules; also treat as standalone when present on sys.
    if getattr(sys, "__compiled__", None) is not None:
        return True
    if hasattr(sys, "_MEIPASS"):
        return True
    executable = str(getattr(sys, "executable", "") or "").strip()
    if not executable:
        return False
    exe_name = os.path.basename(executable).lower()
    return exe_name.endswith(".exe") and exe_name not in {"python.exe", "pythonw.exe", "py.exe"}


def get_app_install_dir() -> str:
    """Directory containing the app entrypoint (repo root in dev, exe dir when packaged)."""
    if _is_standalone_app():
        # Prefer module filename: avoids 8.3 short paths from some launchers/Nuitka.
        module_dir = _windows_module_dir()
        if module_dir:
            return resolve_windows_long_path(module_dir)
        return resolve_windows_long_path(os.path.dirname(os.path.abspath(sys.executable)))
    # src/infra/paths.py -> repo root is parents[2]
    return resolve_windows_long_path(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )


def get_resource_path(relative_path):
    relative_path = str(relative_path or "").replace("/", os.sep)
    if hasattr(sys, "_MEIPASS"):
        bundled = os.path.join(sys._MEIPASS, relative_path)
        if os.path.exists(bundled):
            return resolve_windows_long_path(bundled)
    return resolve_windows_long_path(os.path.join(get_app_install_dir(), relative_path))


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
