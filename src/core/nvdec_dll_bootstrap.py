"""Windows DLL search paths required before importing PyNvVideoCodec."""
from __future__ import annotations

import os
import site
import sys

_ADDED_DIRS: set[str] = set()


def ensure_pynvvideocodec_dll_paths() -> None:
    """Register CUDA 12 runtime + package dirs for ``import PyNvVideoCodec`` on Windows."""
    if not hasattr(os, "add_dll_directory"):
        return

    candidates: list[str] = []
    prefixes = [getattr(sys, "prefix", "")]
    try:
        prefixes.extend(site.getsitepackages())
    except Exception:
        pass
    user_site = site.getusersitepackages()
    if isinstance(user_site, str):
        prefixes.append(user_site)
    elif isinstance(user_site, (list, tuple)):
        prefixes.extend(user_site)

    for base in prefixes:
        if not base:
            continue
        candidates.append(os.path.join(base, "nvidia", "cuda_runtime", "bin"))
        candidates.append(os.path.join(base, "PyNvVideoCodec"))

    cuda_path = os.environ.get("CUDA_PATH", "").strip()
    if cuda_path:
        candidates.extend(
            [
                os.path.join(cuda_path, "bin", "x64"),
                os.path.join(cuda_path, "bin"),
                os.path.join(cuda_path, "lib", "x64"),
            ]
        )

    for path in candidates:
        norm = os.path.normcase(os.path.abspath(path))
        if norm in _ADDED_DIRS or not os.path.isdir(path):
            continue
        os.add_dll_directory(path)
        _ADDED_DIRS.add(norm)
