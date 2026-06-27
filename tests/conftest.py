"""Shared pytest hooks for the VideoSeek test suite."""

from __future__ import annotations

import importlib.util
import sys

# Real packages must not remain replaced by lightweight import stubs.
_PROTECTED_MODULES = frozenset({"numpy", "cv2", "onnxruntime", "faiss", "PySide6"})
_UI_STUB_MODULES = frozenset({"ui.dialogs", "ui.workers", "ui.views.table_views"})


def _is_fake_module(module) -> bool:
    return getattr(module, "__file__", None) is None


def _ensure_real_module(name: str) -> None:
    if name not in sys.modules:
        return
    if not _is_fake_module(sys.modules[name]):
        return
    try:
        installed = importlib.util.find_spec(name) is not None
    except ValueError:
        installed = True
    if not installed:
        return
    del sys.modules[name]
    if name == "PySide6":
        for key in list(sys.modules):
            if key.startswith("PySide6."):
                del sys.modules[key]


def pytest_configure(config) -> None:
    for module_name in _PROTECTED_MODULES:
        _ensure_real_module(module_name)


def pytest_runtest_setup(item) -> None:
    nodeid = item.nodeid.replace("\\", "/")
    if "test_z_qt_controllers.py" in nodeid:
        return
    for module_name in _PROTECTED_MODULES:
        _ensure_real_module(module_name)
    for module_name in _UI_STUB_MODULES:
        _ensure_real_module(module_name)
