"""Shared pytest hooks for the VideoSeek test suite."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock, Mock, NonCallableMagicMock

# Point config I/O at a temp file before any test imports load_config().
# VIDEOSEEK_CONFIG_PATH already set by the caller is left alone.
if not os.environ.get("VIDEOSEEK_CONFIG_PATH", "").strip():
    _pytest_config_dir = Path(tempfile.mkdtemp(prefix="videoseek-pytest-config-"))
    os.environ["VIDEOSEEK_CONFIG_PATH"] = str(_pytest_config_dir / "config.json")

# Real packages must not remain replaced by lightweight import stubs.
_PROTECTED_MODULES = frozenset({"numpy", "cv2", "onnxruntime", "faiss", "PySide6"})
_UI_STUB_MODULES = frozenset({"ui.dialogs", "ui.workers", "ui.views.table_views"})
_FAKE_MODULE_TYPES = (types.SimpleNamespace, MagicMock, Mock, NonCallableMagicMock)


def _is_fake_module(module) -> bool:
    if module is None:
        return True
    if isinstance(module, _FAKE_MODULE_TYPES):
        return True
    file_attr = getattr(module, "__file__", None)
    if file_attr is None:
        return True
    # MagicMock attribute access returns another mock, not a real path string.
    if isinstance(file_attr, _FAKE_MODULE_TYPES) or not isinstance(file_attr, str):
        return True
    return False


def _ensure_real_module(name: str) -> None:
    if name not in sys.modules:
        return
    if not _is_fake_module(sys.modules[name]):
        return
    try:
        installed = importlib.util.find_spec(name) is not None
    except ValueError:
        # Broken stubs (e.g. MagicMock) can make find_spec raise; drop them anyway.
        installed = True
    if not installed:
        return
    del sys.modules[name]
    prefix = f"{name}."
    for key in list(sys.modules):
        if key.startswith(prefix):
            del sys.modules[key]


def _restore_protected_modules() -> None:
    for module_name in _PROTECTED_MODULES:
        _ensure_real_module(module_name)
    for module_name in _UI_STUB_MODULES:
        _ensure_real_module(module_name)


def pytest_configure(config) -> None:
    import os

    os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")
    _restore_protected_modules()


def pytest_collectstart(collector) -> None:
    # Collection imports every test module before any setup hook runs. Restore
    # here so one file's sys.modules stubs cannot poison the next file's import.
    _restore_protected_modules()


def pytest_runtest_setup(item) -> None:
    _restore_protected_modules()
