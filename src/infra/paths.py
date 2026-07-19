"""App install / data / resource path helpers."""

from __future__ import annotations

import os
import sys


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
        return os.path.dirname(os.path.abspath(sys.executable))
    # src/infra/paths.py -> repo root is parents[2]
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_resource_path(relative_path):
    relative_path = str(relative_path or "").replace("/", os.sep)
    if hasattr(sys, "_MEIPASS"):
        bundled = os.path.join(sys._MEIPASS, relative_path)
        if os.path.exists(bundled):
            return bundled
    return os.path.join(get_app_install_dir(), relative_path)


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
