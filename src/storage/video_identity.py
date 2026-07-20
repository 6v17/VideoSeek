"""Library path canonicalization and video identity hashes."""

from __future__ import annotations

import hashlib
import os


def canonicalize_library_path(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


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
