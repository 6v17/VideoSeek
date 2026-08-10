"""Windows helpers to spawn child processes without flashing a console/GUI window."""

from __future__ import annotations

import os
import subprocess
from typing import Any


def hidden_subprocess_kwargs() -> dict[str, Any]:
    """Kwargs for ``subprocess.run`` / ``Popen`` that hide console windows on Windows.

    Safe to splat on non-Windows (returns empty dict).
    """
    if os.name != "nt":
        return {}
    kwargs: dict[str, Any] = {}
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        # SW_HIDE — required for GUI-subsystem children (CREATE_NO_WINDOW alone is not enough).
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    kwargs["creationflags"] = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
    return kwargs
