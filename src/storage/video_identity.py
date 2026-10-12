"""Library path canonicalization and video identity hashes."""

from __future__ import annotations

import hashlib
import os


def canonicalize_library_path(path):
    """Shared path key: strip + expanduser + abspath + normpath + normcase.

    Same semantics as ``normalize_scope_path`` so library roots and search-scope
    file paths cannot diverge on ``~`` / surrounding whitespace.
    """
    text = str(path or "").strip()
    return os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(text))))


def rewrite_path_under_library_root(path: str, old_root: str, new_root: str) -> str | None:
    """If ``path`` is under ``old_root``, return the same relative path under ``new_root``.

    Returns ``None`` when ``path`` is empty or not under ``old_root``.
    """
    raw = str(path or "").strip()
    old = str(old_root or "").strip()
    new = str(new_root or "").strip()
    if not raw or not old or not new:
        return None
    path_abs = os.path.normpath(os.path.abspath(os.path.expanduser(raw)))
    old_abs = os.path.normpath(os.path.abspath(os.path.expanduser(old)))
    new_abs = os.path.normpath(os.path.abspath(os.path.expanduser(new)))
    path_key = os.path.normcase(path_abs)
    old_key = os.path.normcase(old_abs)
    if path_key == old_key:
        return new_abs
    try:
        rel = os.path.relpath(path_abs, start=old_abs)
    except ValueError:
        return None
    if not rel or rel == ".":
        return new_abs
    if rel == ".." or rel.startswith(".." + os.sep):
        return None
    return os.path.normpath(os.path.join(new_abs, rel))


def canonicalize_library_rel_path(rel_path) -> str:
    """Normalize in-library relative paths to forward slashes.

    Meta / SQLite store ``files`` keys with ``/`` (see profile_library_store).
    ``os.path.relpath`` on Windows yields ``\\``, which must not be used for dict lookup.
    """
    return str(rel_path or "").replace("\\", "/").strip()


def get_legacy_video_hash(video_path):
    """Pre-v2 video id: SHA256 of the first 10 MiB only (size/mtime not included)."""
    digest = hashlib.sha256()
    with open(video_path, "rb") as handle:
        digest.update(handle.read(10 * 1024 * 1024))
    return digest.hexdigest()


def get_video_hash(video_path):
    digest = hashlib.sha256()
    stat = os.stat(video_path)
    digest.update(str(int(stat.st_size)).encode("utf-8"))
    mtime_ns = getattr(stat, "st_mtime_ns", int(float(stat.st_mtime) * 1_000_000_000))
    digest.update(str(int(mtime_ns)).encode("utf-8"))
    with open(video_path, "rb") as handle:
        digest.update(handle.read(10 * 1024 * 1024))
    return digest.hexdigest()
