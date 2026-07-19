"""Atomic meta.json load / save helpers."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time

from src.app.logging_utils import get_logger
from src.infra.paths import ensure_folder_exists

logger = get_logger("meta_io")


def _commit_meta_file(temp_path, meta_file):
    """Commit a finished temp JSON file to ``meta_file`` with Windows-friendly retries."""
    if os.path.normcase(os.path.abspath(temp_path)) == os.path.normcase(os.path.abspath(meta_file)):
        return

    attempts = 8 if os.name == "nt" else 3
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            if os.path.exists(meta_file):
                try:
                    os.chmod(meta_file, 0o666)
                except OSError:
                    pass
            os.replace(temp_path, meta_file)
            return
        except PermissionError as exc:
            last_exc = exc
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) == 5:
                last_exc = exc
            else:
                raise
        if attempt < attempts:
            logger.warning(
                "Retrying metadata commit (%s/%s): %s",
                attempt,
                attempts,
                meta_file,
            )
            time.sleep(min(0.05 * attempt, 0.4))

    try:
        shutil.copy2(temp_path, meta_file)
        logger.warning("Metadata commit used copy fallback: %s", meta_file)
        return
    except Exception as copy_exc:
        if last_exc is not None:
            raise last_exc from copy_exc
        raise


def save_meta(meta, meta_file, *, pretty: bool = True):
    """Atomically write ``meta.json``.

    Use ``pretty=False`` on hot scan flushes — compact JSON is much smaller/faster
    at 10k+ videos. Final/user-facing saves can keep ``pretty=True``.
    """
    ensure_folder_exists(meta_file)
    folder = os.path.dirname(meta_file) or "."
    fd, temp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=folder)
    os.close(fd)
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            if pretty:
                json.dump(meta, handle, indent=4, ensure_ascii=False)
            else:
                json.dump(meta, handle, ensure_ascii=False, separators=(",", ":"))
        _commit_meta_file(temp_path, meta_file)
        temp_path = ""
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def load_meta(meta_file):
    if not os.path.exists(meta_file):
        return {"libraries": {}}

    try:
        with open(meta_file, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise RuntimeError(f"Failed to load metadata file: {meta_file}") from exc

    if "libraries" not in data:
        data["libraries"] = {}
    return data
