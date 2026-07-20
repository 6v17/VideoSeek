import json
import os
import shutil
import time

from src.app.config import build_data_storage_paths, get_configured_data_root, load_config, save_config
from src.storage.config_store import get_effective_model_dir
from src.app.logging_utils import get_logger
from src.storage.asset_store import load_metadata
from src.storage.config_store import get_config_schema_version, get_model_profile_storage_paths

logger = get_logger("storage_service")
STORAGE_DIR_NAME = "data"
STAGING_DIR_NAME = ".videoseek-migrate-staging"
MODELS_DIR_NAME = "models"


def _emit(progress_callback, percent, message):
    if not callable(progress_callback):
        return
    try:
        progress_callback(int(max(0, min(100, percent))), str(message or ""))
    except Exception:
        logger.debug("progress_callback failed", exc_info=True)


def _count_files(path):
    if not path or not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        return 1
    total = 0
    for _root, _dirs, files in os.walk(path):
        total += len(files)
    return total


class _CopyProgress:
    def __init__(self, progress_callback, *, total_files, percent_start=5, percent_end=90, label="正在复制文件"):
        self.progress_callback = progress_callback
        self.total_files = max(0, int(total_files or 0))
        self.done = 0
        self.percent_start = int(percent_start)
        self.percent_end = int(percent_end)
        self.label = str(label or "正在复制文件")
        self._last_emit_at = 0.0
        self._last_percent = -1

    def tick(self, rel_name=""):
        self.done += 1
        if not callable(self.progress_callback):
            return
        span = max(1, self.percent_end - self.percent_start)
        if self.total_files <= 0:
            percent = self.percent_start
        else:
            ratio = min(1.0, self.done / float(self.total_files))
            percent = self.percent_start + int(ratio * span)
        now = time.monotonic()
        if percent == self._last_percent and (now - self._last_emit_at) < 0.12 and self.done < self.total_files:
            return
        self._last_percent = percent
        self._last_emit_at = now
        name = str(rel_name or "").replace("\\", "/")
        if name and len(name) > 48:
            name = "…" + name[-47:]
        detail = f"{self.done}/{self.total_files}" if self.total_files else str(self.done)
        if name:
            message = f"{self.label}（{detail}）：{name}"
        else:
            message = f"{self.label}（{detail}）"
        _emit(self.progress_callback, percent, message)


def _copy_tree(src_dir, dst_dir, *, progress=None, rel_prefix=""):
    if not os.path.exists(src_dir):
        return
    for current_root, _dirs, files in os.walk(src_dir):
        rel_root = os.path.relpath(current_root, src_dir)
        target_root = dst_dir if rel_root == "." else os.path.join(dst_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)
        for name in files:
            src_file = os.path.join(current_root, name)
            dst_file = os.path.join(target_root, name)
            shutil.copy2(src_file, dst_file)
            if progress is not None:
                if rel_root == ".":
                    rel_name = os.path.join(rel_prefix, name) if rel_prefix else name
                else:
                    nested = os.path.join(rel_root, name)
                    rel_name = os.path.join(rel_prefix, nested) if rel_prefix else nested
                progress.tick(rel_name)


def _copy_path(src_path, dst_path, *, progress=None, rel_prefix=""):
    if not src_path or not os.path.exists(src_path):
        return
    if os.path.isdir(src_path):
        _copy_tree(src_path, dst_path, progress=progress, rel_prefix=rel_prefix)
        return
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    shutil.copy2(src_path, dst_path)
    if progress is not None:
        progress.tick(rel_prefix or os.path.basename(src_path))


def _remove_tree_if_exists(path):
    if not path or not os.path.exists(path):
        return
    shutil.rmtree(path, ignore_errors=True)


def _ensure_target_available(target_source_dir):
    if not os.path.exists(target_source_dir):
        return
    if os.path.isdir(target_source_dir) and not os.listdir(target_source_dir):
        return
    raise ValueError("Target data directory already exists and is not empty")


def _assert_not_nested_path(current_root, target_root):
    normalized_current = os.path.normcase(os.path.normpath(current_root))
    normalized_target = os.path.normcase(os.path.normpath(target_root))
    try:
        common_path = os.path.commonpath([normalized_current, normalized_target])
    except ValueError:
        return
    if common_path in {normalized_current, normalized_target} and normalized_current != normalized_target:
        raise ValueError("Target data directory cannot be nested inside the current data directory or vice versa")


def _validate_target_metadata(target_meta_file):
    if not os.path.exists(target_meta_file):
        return
    try:
        with open(target_meta_file, encoding="utf-8") as handle:
            json.load(handle)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Data migration failed: invalid metadata JSON ({exc})") from exc
    except OSError as exc:
        raise RuntimeError(f"Data migration failed: cannot read metadata ({exc})") from exc
    load_metadata(target_meta_file)


def _resolve_expected_meta_file(config, target_root):
    schema_version = get_config_schema_version(config=config)
    if schema_version >= 2:
        target_config = dict(config)
        target_config["data_root"] = target_root
        return get_model_profile_storage_paths(config=target_config)["meta_file"]
    target_paths = build_data_storage_paths(target_root)
    return target_paths["meta_file"]


def _resolve_expected_library_markers(config, target_root):
    """Paths that prove profile data landed (meta.json and/or library.db)."""
    meta_file = _resolve_expected_meta_file(config, target_root)
    markers = [meta_file]
    profile_base = os.path.dirname(meta_file)
    if profile_base:
        markers.append(os.path.join(profile_base, "library.db"))
    # Legacy layout also kept a root data/meta.json.
    target_paths = build_data_storage_paths(target_root)
    root_meta = target_paths.get("meta_file")
    if root_meta and root_meta not in markers:
        markers.append(root_meta)
    return [path for path in markers if path]


def _assert_migrated_metadata_present(config, staging_root):
    markers = _resolve_expected_library_markers(config, staging_root)
    existing = [path for path in markers if os.path.exists(path)]
    if not existing:
        preview = ", ".join(markers[:3]) if markers else "(none)"
        raise RuntimeError(
            "Data migration failed: library metadata was not found after transfer "
            f"(looked for: {preview})."
        )
    # Prefer validating JSON meta when present; library.db alone is enough for schema v2.
    for path in existing:
        if str(path).lower().endswith(".json"):
            _validate_target_metadata(path)
            return
    return


def _normalize_existing_path(value):
    path = str(value or "").strip()
    if not path:
        return ""
    return os.path.normpath(os.path.abspath(os.fspath(path)))


def _path_is_strict_descendant(ancestor, descendant):
    """True if descendant is a proper subpath of ancestor (same normalized root)."""
    a = _normalize_existing_path(ancestor)
    d = _normalize_existing_path(descendant)
    if not a or not d or os.path.normcase(a) == os.path.normcase(d):
        return False
    try:
        common = os.path.commonpath([a, d])
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(a)


def _same_volume(path_a, path_b) -> bool:
    """True when both paths are on the same drive / filesystem (rename/move is cheap)."""
    a = _normalize_existing_path(path_a)
    b = _normalize_existing_path(path_b)
    if not a or not b:
        return False
    if os.name == "nt":
        drive_a = os.path.splitdrive(a)[0].upper()
        drive_b = os.path.splitdrive(b)[0].upper()
        return bool(drive_a) and drive_a == drive_b

    def _probe_dev(path: str):
        probe = path
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        if not probe or not os.path.exists(probe):
            raise OSError("no existing ancestor")
        return os.stat(probe).st_dev

    try:
        return _probe_dev(a) == _probe_dev(b)
    except OSError:
        return False


def _prepare_move_destination(dst_path: str) -> None:
    """Ensure ``dst_path`` does not exist so ``shutil.move(src, dst)`` renames into place."""
    if not os.path.exists(dst_path):
        parent = os.path.dirname(dst_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return
    if os.path.isdir(dst_path) and not os.listdir(dst_path):
        os.rmdir(dst_path)
        parent = os.path.dirname(dst_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return
    raise ValueError("Target data directory already exists and is not empty")


def _move_path(src_path: str, dst_path: str) -> None:
    _prepare_move_destination(dst_path)
    shutil.move(src_path, dst_path)


def _can_same_volume_move(copy_tasks, target_root: str) -> bool:
    for src, dst in copy_tasks:
        if not src or not os.path.exists(src):
            continue
        if not _same_volume(src, dst or target_root):
            return False
    return True


def _collect_storage_copy_tasks(config, current_data_root, target_root):
    target_paths = build_data_storage_paths(target_root)
    current_storage_dir = ""
    meta_file = _normalize_existing_path(config.get("meta_file", ""))
    if meta_file:
        current_storage_dir = os.path.dirname(meta_file)
    if not current_storage_dir:
        current_storage_dir = os.path.join(current_data_root, STORAGE_DIR_NAME)

    copy_tasks = []
    seen_pairs = set()

    source_pair = (
        _normalize_existing_path(current_storage_dir),
        _normalize_existing_path(os.path.dirname(target_paths["meta_file"])),
    )
    if source_pair[0]:
        copy_tasks.append(source_pair)
        seen_pairs.add(source_pair)

    for key, target_path in target_paths.items():
        current_path = _normalize_existing_path(config.get(key, ""))
        if not current_path:
            continue
        pair = (current_path, _normalize_existing_path(target_path))
        if pair in seen_pairs:
            continue
        if pair[0] == source_pair[0]:
            continue
        copy_tasks.append(pair)
        seen_pairs.add(pair)

    return current_storage_dir, target_paths, copy_tasks


def migrate_app_data_root(target_root, progress_callback=None):
    normalized_target_root = os.path.normpath(os.path.abspath(os.fspath(target_root)))
    if not normalized_target_root:
        raise ValueError("Target data directory is required")

    _emit(progress_callback, 1, "正在准备数据搬家")
    config = load_config()
    current_data_root = get_configured_data_root(config)
    if os.path.normcase(normalized_target_root) == os.path.normcase(current_data_root):
        _emit(progress_callback, 100, "无需搬家")
        return {
            "migrated": False,
            "reason": "same_path",
            "data_root": current_data_root,
            "transfer_mode": "",
            "old_remaining": False,
        }

    staging_root = os.path.join(normalized_target_root, STAGING_DIR_NAME)
    current_storage_dir, staging_paths, copy_tasks = _collect_storage_copy_tasks(
        config,
        current_data_root,
        staging_root,
    )
    target_paths = build_data_storage_paths(normalized_target_root)
    target_storage_dir = os.path.dirname(target_paths["meta_file"])
    staging_storage_dir = os.path.dirname(staging_paths["meta_file"])

    _assert_not_nested_path(current_data_root, normalized_target_root)
    for current_path, _target_path in copy_tasks:
        _assert_not_nested_path(current_path, normalized_target_root)
    _ensure_target_available(target_storage_dir)
    os.makedirs(normalized_target_root, exist_ok=True)
    _remove_tree_if_exists(staging_root)

    use_move = _can_same_volume_move(copy_tasks, normalized_target_root)
    transfer_mode = "move" if use_move else "copy"
    moved_pairs = []

    source_meta = _normalize_existing_path(config.get("meta_file", "")) or os.path.join(
        current_storage_dir, "meta.json"
    )
    if source_meta and os.path.exists(source_meta):
        _emit(progress_callback, 2, "正在校验源数据元数据")
        _validate_target_metadata(source_meta)

    logger.info(
        "Migrating application data root from %s to %s (%s)",
        current_data_root,
        normalized_target_root,
        transfer_mode,
    )
    try:
        if use_move:
            _emit(progress_callback, 10, "同盘剪切：正在移动数据（几乎不占双倍空间）")
            for current_path, target_path in copy_tasks:
                if not current_path or not os.path.exists(current_path):
                    continue
                _move_path(current_path, target_path)
                moved_pairs.append((current_path, target_path))
            _emit(progress_callback, 70, "正在校验元数据")
        else:
            _emit(progress_callback, 3, "跨盘复制：正在统计待复制文件")
            total_files = sum(_count_files(src) for src, _dst in copy_tasks)
            progress = _CopyProgress(
                progress_callback,
                total_files=total_files,
                percent_start=5,
                percent_end=88,
                label="正在复制数据",
            )
            _emit(progress_callback, 5, f"开始复制（共 {total_files} 个文件）")
            for current_path, target_path in copy_tasks:
                _copy_path(
                    current_path,
                    target_path,
                    progress=progress,
                    rel_prefix=os.path.basename(current_path) or "data",
                )
            _emit(progress_callback, 90, "正在校验元数据")

        _assert_migrated_metadata_present(config, staging_root)
        _emit(progress_callback, 94, "正在切换到新数据目录")
        if os.path.exists(staging_storage_dir):
            _prepare_move_destination(target_storage_dir)
            shutil.move(staging_storage_dir, target_storage_dir)
            if use_move:
                moved_pairs = [
                    (src, target_storage_dir if dst == staging_storage_dir else dst)
                    for src, dst in moved_pairs
                ]
    except Exception:
        if use_move:
            for src, dst in reversed(moved_pairs):
                try:
                    if os.path.exists(dst) and not os.path.exists(src):
                        _move_path(dst, src)
                except Exception:
                    logger.exception("Failed to roll back moved path %s -> %s", dst, src)
        _remove_tree_if_exists(staging_root)
        raise
    finally:
        if os.path.isdir(staging_root) and not os.listdir(staging_root):
            _remove_tree_if_exists(staging_root)

    old_remaining = (not use_move) and bool(current_storage_dir) and os.path.exists(current_storage_dir)
    _emit(progress_callback, 97, "正在更新配置")
    updated_config = dict(config)
    updated_config["data_root"] = normalized_target_root
    if old_remaining:
        updated_config["pending_cleanup_data_root"] = current_data_root
    else:
        updated_config.pop("pending_cleanup_data_root", None)
    save_config(updated_config)
    _emit(progress_callback, 100, "数据搬家完成" if use_move else "数据复制完成，可确认是否删除旧数据")
    return {
        "migrated": True,
        "reason": "",
        "transfer_mode": transfer_mode,
        "old_remaining": old_remaining,
        "old_data_root": current_data_root,
        "new_data_root": normalized_target_root,
        "old_data_dir": current_storage_dir,
        "new_data_dir": target_storage_dir,
    }


def migrate_model_root(target_root, progress_callback=None):
    """Move or copy the active profile's model tree to a new root and retarget profiles."""
    normalized_target = _normalize_existing_path(target_root)
    if not normalized_target:
        raise ValueError("Target model directory is required")

    _emit(progress_callback, 1, "正在准备模型搬家")
    config = load_config()
    source = _normalize_existing_path(get_effective_model_dir(config=config))
    if not source:
        raise ValueError("Active profile has no runtime.model_dir")

    if os.path.normcase(source) == os.path.normcase(normalized_target):
        _emit(progress_callback, 100, "无需搬家")
        return {
            "migrated": False,
            "reason": "same_path",
            "transfer_mode": "",
            "old_remaining": False,
            "old_model_dir": source,
            "new_model_dir": normalized_target,
        }

    if not os.path.isdir(source):
        raise ValueError("Current model directory does not exist or is not a folder")

    _assert_not_nested_path(source, normalized_target)
    _assert_not_nested_path(normalized_target, source)

    if os.path.exists(normalized_target):
        try:
            entries = os.listdir(normalized_target)
        except OSError as exc:
            raise ValueError("Cannot read target model directory") from exc
        if entries:
            raise ValueError("Target model directory must be empty or not exist yet")

    use_move = _same_volume(source, normalized_target)
    transfer_mode = "move" if use_move else "copy"

    if use_move:
        _emit(progress_callback, 20, "同盘剪切：正在移动模型目录")
        _move_path(source, normalized_target)
    else:
        os.makedirs(normalized_target, exist_ok=True)
        _emit(progress_callback, 3, "跨盘复制：正在统计待复制文件")
        total_files = _count_files(source)
        progress = _CopyProgress(
            progress_callback,
            total_files=total_files,
            percent_start=5,
            percent_end=90,
            label="正在复制模型",
        )
        _emit(progress_callback, 5, f"开始复制（共 {total_files} 个文件）")
        _copy_tree(source, normalized_target, progress=progress)

    _emit(progress_callback, 94, "正在更新模型路径配置")
    old_normcase = os.path.normcase(source)
    updated_config = dict(config)
    top = _normalize_existing_path(updated_config.get("model_dir", ""))
    if top and os.path.normcase(top) == old_normcase:
        updated_config["model_dir"] = normalized_target

    models = updated_config.get("models")
    if isinstance(models, dict):
        profiles = models.get("profiles")
        if isinstance(profiles, list):
            for idx, item in enumerate(profiles):
                if not isinstance(item, dict):
                    continue
                runtime = item.get("runtime")
                if not isinstance(runtime, dict):
                    continue
                md = _normalize_existing_path(runtime.get("model_dir", ""))
                if not md or os.path.normcase(md) != old_normcase:
                    continue
                new_runtime = dict(runtime)
                new_runtime["model_dir"] = normalized_target
                new_item = dict(item)
                new_item["runtime"] = new_runtime
                profiles[idx] = new_item

    old_remaining = (not use_move) and os.path.exists(source)
    if old_remaining:
        updated_config["pending_cleanup_model_dir"] = source
    else:
        updated_config.pop("pending_cleanup_model_dir", None)
    save_config(updated_config)
    _emit(progress_callback, 100, "模型搬家完成" if use_move else "模型复制完成，可确认是否删除旧目录")
    return {
        "migrated": True,
        "reason": "",
        "transfer_mode": transfer_mode,
        "old_remaining": old_remaining,
        "old_model_dir": source,
        "new_model_dir": normalized_target,
    }


def cleanup_old_model_dir(pending_root, active_model_dir=None):
    """Remove a former model root directory tree left after migrate_model_root. Refuses if still in use."""
    pending = _normalize_existing_path(pending_root)
    if not pending:
        raise ValueError("Path to clean up is required")

    config = load_config()
    active = _normalize_existing_path(active_model_dir or get_effective_model_dir(config=config))
    if not active:
        raise ValueError("Active model directory is unknown")

    if os.path.normcase(pending) == os.path.normcase(active):
        raise ValueError("Cannot remove the active model directory")

    if _path_is_strict_descendant(pending, active):
        raise ValueError("Current model directory is under the path to remove")

    if _path_is_strict_descendant(active, pending):
        raise ValueError("Refusing to remove a folder inside the active model directory")

    if not os.path.exists(pending):
        return {
            "cleaned": False,
            "reason": "missing",
            "old_model_dir": pending,
        }

    shutil.rmtree(pending)
    return {
        "cleaned": True,
        "reason": "",
        "old_model_dir": pending,
    }


def cleanup_old_data_root(target_root, active_data_root=None):
    normalized_target_root = os.path.normpath(os.path.abspath(os.fspath(target_root)))
    if not normalized_target_root:
        raise ValueError("Target data directory is required")

    current_root = os.path.normpath(active_data_root or get_configured_data_root())
    if os.path.normcase(normalized_target_root) == os.path.normcase(current_root):
        raise ValueError("Cannot clean the active data directory")

    target_paths = build_data_storage_paths(normalized_target_root)
    target_data_dir = os.path.dirname(target_paths["meta_file"])
    target_models_dir = os.path.join(normalized_target_root, MODELS_DIR_NAME)
    staging_dir = os.path.join(normalized_target_root, STAGING_DIR_NAME)
    configured_model_dir = _normalize_existing_path(load_config().get("model_dir", ""))

    removed_any = False
    if os.path.exists(target_data_dir):
        shutil.rmtree(target_data_dir)
        removed_any = True
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir, ignore_errors=True)
        removed_any = True
    can_remove_models_dir = True
    if configured_model_dir and os.path.exists(target_models_dir):
        try:
            common_model_root = os.path.commonpath([configured_model_dir, _normalize_existing_path(target_models_dir)])
        except ValueError:
            common_model_root = ""
        if common_model_root == _normalize_existing_path(target_models_dir):
            can_remove_models_dir = False
    if can_remove_models_dir and os.path.exists(target_models_dir):
        shutil.rmtree(target_models_dir, ignore_errors=True)
        removed_any = True

    return {
        "cleaned": removed_any,
        "reason": "" if removed_any else "missing",
        "old_data_root": normalized_target_root,
        "old_data_dir": target_data_dir,
    }
