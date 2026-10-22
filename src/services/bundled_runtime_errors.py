"""User-facing bundled runtime import error classification."""

from __future__ import annotations

import os


def classify_bundled_import_error(error: str) -> str:
    detail = str(error or "").strip().lower()
    if not detail:
        return "generic"

    disk_markers = (
        "disk_full",
        "no space left",
        "not enough space",
        "disk full",
        "disk quota exceeded",
        "errno 28",
        "os error 28",
        "winerror 112",
        "there is not enough space",
        "空间不足",
        "磁盘空间",
    )
    if any(marker in detail for marker in disk_markers):
        return "disk_full"

    permission_markers = (
        "permission denied",
        "access is denied",
        "errno 13",
        "os error 13",
        "winerror 5",
        "拒绝访问",
    )
    if any(marker in detail for marker in permission_markers):
        return "permission_denied"

    corrupt_markers = (
        "bad zip",
        "not a zip",
        "badzipfile",
        "corrupt",
        "checksum",
        "sha256",
        "unrecognized package",
    )
    if any(marker in detail for marker in corrupt_markers):
        return "corrupt_package"

    if "missing bundled files" in detail:
        return "missing_seed"

    return "generic"


def format_bundled_import_error(error: str, texts: dict | None = None) -> str:
    """Map raw exception text to a short user message (optional i18n ``texts`` dict)."""
    code = classify_bundled_import_error(error)
    raw = str(error or "").strip()
    t = dict(texts or {})
    if code == "disk_full":
        return t.get(
            "runtime_bundled_error_disk_full",
            "Not enough disk space to unpack bundled resources. Free space on the system drive "
            "(usually C:) and under your VideoSeek data folder, then quit and reopen VideoSeek—the "
            "Full edition will import again automatically on startup.",
        )
    if code == "permission_denied":
        base = t.get(
            "runtime_bundled_error_permission",
            "Import failed: access denied. Try running VideoSeek as a normal user (not Program Files "
            "write-only) or choose a writable model folder in Settings.",
        )
        return _append_restart_hint(base, t)
    if code == "corrupt_package":
        return t.get(
            "runtime_bundled_error_corrupt",
            "A bundled resource file looks damaged or incomplete. Reinstall the Full setup or "
            "import the zip manually from Settings.",
        )
    if code == "missing_seed":
        return t.get(
            "runtime_bundled_error_missing_seed",
            "The Full edition runtime folder beside VideoSeek.exe is incomplete. Reinstall the Full setup.",
        )
    detail = raw[:320] if raw else t.get("runtime_bundled_error_generic", "Bundled import failed.")
    base = t.get("runtime_bundled_bootstrap_failed", "Bundled resource import failed: {error}").format(
        error=detail
    )
    return _append_restart_hint(base, t)


def _append_restart_hint(message: str, texts: dict) -> str:
    base = str(message or "").strip()
    hint = str(texts.get("runtime_bundled_error_restart_hint") or "").strip()
    if not hint or hint in base:
        return base
    return f"{base}\n\n{hint}"


def estimate_bundled_import_bytes(paths: list[str]) -> int:
    total = 0
    for path in paths:
        try:
            if os.path.isfile(path):
                total += int(os.path.getsize(path))
        except OSError:
            continue
    # Extracted models land under AppData; reserve headroom for unzip temp files.
    return int(total * 1.35) + (128 * 1024 * 1024)


def check_disk_space_for_import(paths: list[str], *, target_dir: str) -> str | None:
    """Return an error message when free space is likely insufficient, else None."""
    import shutil

    need = estimate_bundled_import_bytes(paths)
    if need <= 0:
        return None
    root = os.path.abspath(os.path.normpath(str(target_dir or "").strip() or os.getcwd()))
    try:
        usage = shutil.disk_usage(root)
    except OSError as exc:
        return str(exc)
    free = int(usage.free)
    if free >= need:
        return None
    need_mb = max(1, need // (1024 * 1024))
    free_mb = max(0, free // (1024 * 1024))
    return (
        f"disk_full: need about {need_mb} MB free under {root}, "
        f"only {free_mb} MB available ({classify_bundled_import_error('disk full')})"
    )
