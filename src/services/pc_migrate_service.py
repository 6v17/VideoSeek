"""Export / import VideoSeek app data for moving to a new PC.

MVP scope:
- Export ``data/`` + sanitized config snapshot + library path map (no models).
- Import into a target data root, retarget config, then remap missing library roots.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from src.app.config import (
    PATH_KEYS,
    build_data_storage_paths,
    get_app_version,
    get_configured_data_root,
    load_config,
    save_config,
)
from src.app.logging_utils import get_logger
from src.services.storage_service import (
    STORAGE_DIR_NAME,
    _CopyProgress,
    _count_files,
    _copy_tree,
    _emit,
)
from src.storage.video_identity import canonicalize_library_path

logger = get_logger("pc_migrate")

MANIFEST_NAME = "manifest.json"
CONFIG_SNAPSHOT_NAME = "config.snapshot.json"
LIBRARY_MAP_NAME = "library_map.json"
DATA_DIR_NAME = "data"
PC_MIGRATE_FORMAT = "videoseek-pc-migrate"
PC_MIGRATE_VERSION = 1

_SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|token|password|authorization)", re.I)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sanitize_config_for_export(config: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-copy config, redacting secret-looking string values."""

    def _walk(value: Any) -> Any:
        if isinstance(value, Mapping):
            out: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                if _SECRET_KEY_RE.search(key_text):
                    # Drop secret trees entirely (string keys, api_keys maps, etc.).
                    out[key_text] = ""
                else:
                    out[key_text] = _walk(item)
            return out
        if isinstance(value, list):
            return [_walk(item) for item in value]
        return value

    return _walk(dict(config or {}))


def build_library_path_map(*, config=None) -> list[dict[str, Any]]:
    """Collect absolute library roots for remap on the destination PC."""
    from src.services.library_service import list_libraries

    cfg = config or load_config()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(path: str, *, source: str) -> None:
        raw = str(path or "").strip()
        if not raw:
            return
        try:
            canonical = canonicalize_library_path(raw)
        except Exception:
            canonical = os.path.normpath(os.path.abspath(os.path.expanduser(raw)))
        key = os.path.normcase(canonical)
        if key in seen:
            return
        seen.add(key)
        files = {}
        try:
            libs = list_libraries()
            files = dict((libs.get(canonical) or libs.get(raw) or {}).get("files") or {})
        except Exception:
            files = {}
        rows.append(
            {
                "path": canonical,
                "source": source,
                "exists": os.path.isdir(canonical),
                "file_count": len(files),
            }
        )

    try:
        for path in list_libraries().keys():
            _add(path, source="library")
    except Exception as exc:
        logger.warning("Failed listing libraries for migrate map: %s", exc)

    for key in (
        "search_scope_library_paths",
        "dialogue_search_scope_library_paths",
    ):
        for path in list(cfg.get(key) or []):
            _add(str(path), source=key)
    download_target = str(cfg.get("download_target_library") or "").strip()
    if download_target:
        _add(download_target, source="download_target_library")
    return rows


def resolve_current_storage_dir(config=None) -> str:
    cfg = config or load_config()
    meta_file = str(cfg.get("meta_file") or "").strip()
    if meta_file:
        parent = os.path.dirname(os.path.abspath(os.path.expanduser(meta_file)))
        if parent:
            return os.path.normpath(parent)
    data_root = get_configured_data_root(cfg)
    return os.path.normpath(os.path.join(data_root, STORAGE_DIR_NAME))


def export_pc_migrate_bundle(
    dest_dir: str,
    *,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Copy app ``data/`` + snapshots into ``dest_dir`` (folder, not zip)."""
    dest = os.path.normpath(os.path.abspath(os.path.expanduser(str(dest_dir or "").strip())))
    if not dest:
        raise ValueError("export destination is required")
    os.makedirs(dest, exist_ok=True)
    if any(os.scandir(dest)):
        # Allow overwriting only our known layout markers.
        existing = {entry.name for entry in os.scandir(dest)}
        allowed = {MANIFEST_NAME, CONFIG_SNAPSHOT_NAME, LIBRARY_MAP_NAME, DATA_DIR_NAME}
        if existing - allowed:
            raise ValueError("export destination must be empty or a previous migrate bundle")

    _emit(progress_callback, 1, "正在准备导出")
    config = load_config()
    storage_dir = resolve_current_storage_dir(config)
    if not storage_dir or not os.path.isdir(storage_dir):
        raise FileNotFoundError(f"data directory not found: {storage_dir}")

    library_map = build_library_path_map(config=config)
    snapshot = _sanitize_config_for_export(config)
    dest_data = os.path.join(dest, DATA_DIR_NAME)

    _emit(progress_callback, 5, "正在统计文件")
    total_files = _count_files(storage_dir)
    progress = _CopyProgress(
        progress_callback,
        total_files=total_files,
        percent_start=8,
        percent_end=88,
        label="正在导出数据",
    )
    if os.path.isdir(dest_data):
        shutil.rmtree(dest_data, ignore_errors=True)
    _copy_tree(storage_dir, dest_data, progress=progress, rel_prefix=DATA_DIR_NAME)

    _emit(progress_callback, 90, "正在写入清单")
    with open(os.path.join(dest, CONFIG_SNAPSHOT_NAME), "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(dest, LIBRARY_MAP_NAME), "w", encoding="utf-8") as handle:
        json.dump({"libraries": library_map}, handle, ensure_ascii=False, indent=2)

    manifest = {
        "format": PC_MIGRATE_FORMAT,
        "format_version": PC_MIGRATE_VERSION,
        "exported_at": _utc_now_iso(),
        "app_version": get_app_version(),
        "source_data_root": get_configured_data_root(config),
        "source_storage_dir": storage_dir,
        "includes_models": False,
        "file_count": int(total_files),
        "library_count": len(library_map),
    }
    with open(os.path.join(dest, MANIFEST_NAME), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    _emit(progress_callback, 100, "导出完成")
    return {
        "ok": True,
        "dest_dir": dest,
        "manifest": manifest,
        "library_count": len(library_map),
        "file_count": int(total_files),
    }


def load_pc_migrate_manifest(bundle_dir: str) -> dict[str, Any]:
    root = os.path.normpath(os.path.abspath(os.path.expanduser(str(bundle_dir or "").strip())))
    manifest_path = os.path.join(root, MANIFEST_NAME)
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"missing {MANIFEST_NAME}")
    with open(manifest_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or payload.get("format") != PC_MIGRATE_FORMAT:
        raise ValueError("not a VideoSeek PC migrate bundle")
    try:
        format_version = int(payload.get("format_version") or 0)
    except (TypeError, ValueError):
        format_version = 0
    if format_version < 1 or format_version > PC_MIGRATE_VERSION:
        raise ValueError(
            f"unsupported migrate format_version: {payload.get('format_version')!r} "
            f"(this app supports 1..{PC_MIGRATE_VERSION})"
        )
    data_dir = os.path.join(root, DATA_DIR_NAME)
    if not os.path.isdir(data_dir):
        raise FileNotFoundError(f"missing {DATA_DIR_NAME}/ in bundle")
    return payload


def _merge_imported_config(
    snapshot: Mapping[str, Any],
    *,
    target_data_root: str,
    current: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply snapshot preferences onto the new machine without clobbering local paths."""
    live = dict(current or load_config())
    incoming = dict(snapshot or {})

    # Keep machine-local runtime paths.
    preserve_keys = {
        "ffmpeg_path",
        "model_dir",
        "pending_cleanup_data_root",
        "pending_cleanup_model_dir",
        "jianying_drafts_dir",
    }
    preserved = {key: live.get(key) for key in preserve_keys if key in live}

    # Start from live config, overlay non-path preferences from snapshot.
    skip_overlay = set(PATH_KEYS) | preserve_keys | {
        "data_root",
        "data_dir",
        "global_dir",
        "remote_dir",
        "preview_cache_dir",
        "mobile_upload_dir",
        "remote_build_cache_dir",
        "link_cache_dir",
        "downloads_dir",
        "remote_build_report_file",
    }
    for key, value in incoming.items():
        if key in skip_overlay:
            continue
        if _SECRET_KEY_RE.search(str(key)):
            continue
        live[key] = value

    # Keep scope path lists from snapshot so remap can rewrite them.
    for key in (
        "search_scope_library_paths",
        "dialogue_search_scope_library_paths",
        "download_target_library",
    ):
        if key in incoming:
            live[key] = incoming.get(key)

    live["data_root"] = os.path.normpath(os.path.abspath(target_data_root))
    for key, value in build_data_storage_paths(live["data_root"]).items():
        live[key] = value
    for key, value in preserved.items():
        if value is not None:
            live[key] = value
    return live


def import_pc_migrate_bundle(
    bundle_dir: str,
    *,
    target_data_root: str | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Restore ``data/`` from a migrate bundle and retarget config."""
    root = os.path.normpath(os.path.abspath(os.path.expanduser(str(bundle_dir or "").strip())))
    _emit(progress_callback, 1, "正在校验迁移包")
    manifest = load_pc_migrate_manifest(root)
    source_data = os.path.join(root, DATA_DIR_NAME)

    cfg_live = load_config()
    target_root = os.path.normpath(
        os.path.abspath(
            os.path.expanduser(
                str(target_data_root or get_configured_data_root(cfg_live) or "").strip()
            )
        )
    )
    if not target_root:
        raise ValueError("target data root is required")

    target_paths = build_data_storage_paths(target_root)
    target_storage = os.path.dirname(target_paths["meta_file"])
    os.makedirs(target_root, exist_ok=True)

    if os.path.isdir(target_storage) and os.listdir(target_storage):
        raise ValueError(
            f"target data directory is not empty: {target_storage}\n"
            "Import into an empty data root, or move the current data aside first."
        )

    _emit(progress_callback, 5, "正在统计待导入文件")
    total_files = _count_files(source_data)
    progress = _CopyProgress(
        progress_callback,
        total_files=total_files,
        percent_start=8,
        percent_end=82,
        label="正在导入数据",
    )
    _copy_tree(source_data, target_storage, progress=progress, rel_prefix=DATA_DIR_NAME)

    meta_marker = target_paths.get("meta_file") or os.path.join(target_storage, "meta.json")
    has_meta = os.path.isfile(meta_marker)
    has_library_db = False
    for current_root, _dirs, files in os.walk(target_storage):
        if "library.db" in files:
            has_library_db = True
            break
    if not has_meta and not has_library_db:
        raise RuntimeError("imported data is missing meta.json / library.db")

    _emit(progress_callback, 88, "正在合并配置")
    snapshot_path = os.path.join(root, CONFIG_SNAPSHOT_NAME)
    snapshot: dict[str, Any] = {}
    if os.path.isfile(snapshot_path):
        with open(snapshot_path, encoding="utf-8") as handle:
            loaded = json.load(handle)
            if isinstance(loaded, dict):
                snapshot = loaded
    merged = _merge_imported_config(snapshot, target_data_root=target_root, current=cfg_live)
    save_config(merged)

    library_map_path = os.path.join(root, LIBRARY_MAP_NAME)
    library_map: list[dict[str, Any]] = []
    if os.path.isfile(library_map_path):
        with open(library_map_path, encoding="utf-8") as handle:
            payload = json.load(handle)
            library_map = list((payload or {}).get("libraries") or [])

    missing = []
    for row in library_map:
        path = str((row or {}).get("path") or "").strip()
        if path and not os.path.isdir(path):
            missing.append(path)

    _emit(progress_callback, 100, "导入完成")
    return {
        "ok": True,
        "manifest": manifest,
        "target_data_root": target_root,
        "target_storage_dir": target_storage,
        "library_map": library_map,
        "missing_libraries": missing,
        "file_count": int(total_files),
    }


def _iter_library_meta_bases(config=None) -> list[str]:
    """Profile / subtitle store dirs that hold a libraries registry."""
    from src.app.config import get_data_storage_paths
    from src.storage.config_store import get_model_profile_storage_paths
    from src.storage.subtitle_library_store import get_subtitle_library_base_dir

    cfg = config or load_config()
    bases: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        raw = os.path.normpath(str(path or "").strip())
        if not raw:
            return
        key = os.path.normcase(raw)
        if key in seen:
            return
        seen.add(key)
        bases.append(raw)

    try:
        meta_file = str(get_model_profile_storage_paths(config=cfg).get("meta_file") or "").strip()
        if meta_file:
            _add(os.path.dirname(meta_file))
    except Exception as exc:
        logger.debug("active profile base unavailable: %s", exc)

    try:
        _add(get_subtitle_library_base_dir(config=cfg))
    except Exception as exc:
        logger.debug("subtitle library base unavailable: %s", exc)

    try:
        data_dir = str(get_data_storage_paths(config=cfg).get("data_dir") or "").strip()
        model_assets = os.path.join(data_dir, "model_assets") if data_dir else ""
        if model_assets and os.path.isdir(model_assets):
            for root, dirnames, files in os.walk(model_assets):
                if "library.db" in files or "meta.json" in files:
                    _add(root)
                    dirnames.clear()
    except Exception as exc:
        logger.debug("model_assets walk failed: %s", exc)
    return bases


def _remap_libraries_dict(
    libraries: Mapping[str, Any],
    normalized: Mapping[str, str],
) -> tuple[dict[str, Any], int]:
    rewritten: dict[str, Any] = {}
    remapped = 0
    for old_key, payload in dict(libraries or {}).items():
        try:
            old_canon = canonicalize_library_path(old_key)
        except Exception:
            old_canon = str(old_key)
        new_key = normalized.get(old_canon)
        if new_key:
            rewritten[new_key] = dict(payload or {})
            remapped += 1
        else:
            rewritten[old_key] = payload
    return rewritten, remapped


def apply_library_path_remaps(
    remaps: Mapping[str, str],
    *,
    config=None,
) -> dict[str, Any]:
    """Rewrite library roots in metadata + config scopes.

    ``remaps`` maps old absolute roots → new absolute roots on this machine.
    """
    from src.storage.profile_library_store import load_profile_meta, save_profile_meta
    from src.services.search_scope import invalidate_searchable_path_index_cache

    def _abs_preserve(path: str) -> str:
        text = str(path or "").strip()
        if not text:
            return ""
        return os.path.normpath(os.path.abspath(os.path.expanduser(text)))

    # Lookup keys are canonicalize() (normcase); values keep real casing for storage.
    normalized: dict[str, str] = {}
    for old, new in dict(remaps or {}).items():
        old_raw = str(old or "").strip()
        new_raw = str(new or "").strip()
        if not old_raw or not new_raw:
            continue
        old_key = canonicalize_library_path(old_raw)
        new_path = _abs_preserve(new_raw)
        if not old_key or not new_path:
            continue
        if os.path.normcase(old_key) == os.path.normcase(new_path):
            continue
        normalized[old_key] = new_path
    if not normalized:
        return {"ok": True, "remapped": 0, "libraries": 0, "stores": 0}

    cfg = dict(config or load_config())
    remapped = 0
    library_total = 0
    stores = 0
    lance_videos = 0
    transcript_rows = 0
    tag_rows = 0
    for base in _iter_library_meta_bases(cfg):
        try:
            if not os.path.isdir(base) and not os.path.isfile(os.path.join(base, "library.db")):
                if not os.path.isfile(os.path.join(base, "meta.json")):
                    continue
            meta = load_profile_meta(base)
            rewritten, count = _remap_libraries_dict(meta.get("libraries") or {}, normalized)
            meta["libraries"] = rewritten
            save_profile_meta(base, meta)
            remapped += count
            library_total += len(rewritten)
            stores += 1
        except Exception as exc:
            logger.warning("Failed remapping libraries under %s: %s", base, exc)

        # Lance rows keep their own library_path; meta remap alone leaves indexes "missing".
        try:
            from src.storage.lance_store import remap_lance_library_roots

            lance_result = remap_lance_library_roots(base, normalized)
            lance_videos += int((lance_result or {}).get("videos") or 0)
        except Exception as exc:
            logger.warning("Failed remapping Lance library paths under %s: %s", base, exc)

    try:
        from src.storage.dialogue_transcript_store import remap_transcript_library_roots

        transcript_rows = int(
            (remap_transcript_library_roots(normalized, config=cfg) or {}).get("rows") or 0
        )
    except Exception as exc:
        logger.warning("Failed remapping dialogue transcript library paths: %s", exc)

    try:
        from src.storage.evidence_tags_store import remap_tag_library_roots

        tag_rows = int((remap_tag_library_roots(normalized, config=cfg) or {}).get("rows") or 0)
    except Exception as exc:
        logger.warning("Failed remapping evidence tag library paths: %s", exc)

    def _remap_path_list(values: list[Any]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in values:
            raw = str(item or "").strip()
            if not raw:
                continue
            try:
                canon = canonicalize_library_path(raw)
            except Exception:
                canon = raw
            replacement = normalized.get(canon, canon)
            key = os.path.normcase(replacement)
            if key in seen:
                continue
            seen.add(key)
            out.append(replacement)
        return out

    for key in ("search_scope_library_paths", "dialogue_search_scope_library_paths"):
        if key in cfg:
            cfg[key] = _remap_path_list(list(cfg.get(key) or []))
    download_target = str(cfg.get("download_target_library") or "").strip()
    if download_target:
        try:
            canon = canonicalize_library_path(download_target)
        except Exception:
            canon = download_target
        if canon in normalized:
            cfg["download_target_library"] = normalized[canon]
    save_config(cfg)
    try:
        invalidate_searchable_path_index_cache()
    except Exception:
        pass
    return {
        "ok": True,
        "remapped": remapped,
        "libraries": library_total,
        "stores": stores,
        "remap_count": len(normalized),
        "lance_videos": lance_videos,
        "transcript_rows": transcript_rows,
        "tag_rows": tag_rows,
    }


def suggest_export_dir_name() -> str:
    stamp = time.strftime("%Y%m%d-%H%M")
    return f"VideoSeek-migrate-{stamp}"
