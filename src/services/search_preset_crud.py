"""Create, update, and delete shared search presets."""

from __future__ import annotations

import os
import re
import shutil
import uuid

from src.services.search_preset_constants import BUILTIN_SEARCH_PRESET_IDS, IMAGE_EXTENSIONS, PRESET_TYPE_MIXED
from src.services.search_preset_model import (
    normalize_fusion,
    normalize_preset_record,
    preset_has_content,
)
from src.services.search_preset_query import (
    invalidate_all_preset_query_caches,
    resolve_preset_query_vector,
)
from src.services.search_preset_storage import (
    _now_iso,
    _suppressed_builtin_ids,
    get_preset_refs_dir,
    load_presets_document,
    resolve_preset_ref_paths,
    save_presets_document,
)


def _sanitize_preset_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(name or "").strip())
    if not cleaned:
        raise ValueError("Preset name is required")
    if len(cleaned) > 64:
        cleaned = cleaned[:64].strip()
    return cleaned


def _copy_reference_image(source_path: str, preset_id: str, index: int, config=None) -> str:
    source_path = str(source_path or "").strip()
    if not source_path or not os.path.isfile(source_path):
        raise ValueError("Reference image is unreadable")
    ext = os.path.splitext(source_path)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        ext = ".jpg"
    refs_dir = get_preset_refs_dir(config)
    os.makedirs(refs_dir, exist_ok=True)
    dest_path = os.path.join(refs_dir, f"{preset_id}_{index}{ext}")
    shutil.copy2(source_path, dest_path)
    return f"refs/{preset_id}_{index}{ext}"


def _copy_reference_images(source_paths, preset_id: str, config=None) -> list[str]:
    ref_files = []
    for index, source_path in enumerate(list(source_paths or [])):
        path = str(source_path or "").strip()
        if not path:
            continue
        ref_files.append(_copy_reference_image(path, preset_id, index, config=config))
    return ref_files


def _same_reference_paths(left, right) -> bool:
    left_norm = [os.path.normcase(os.path.normpath(str(path or "").strip())) for path in left if str(path or "").strip()]
    right_norm = [os.path.normcase(os.path.normpath(str(path or "").strip())) for path in right if str(path or "").strip()]
    return left_norm == right_norm


def _remove_preset_reference_files(preset: dict, config=None) -> None:
    for ref_path in resolve_preset_ref_paths(preset, config=config):
        if os.path.isfile(ref_path):
            try:
                os.remove(ref_path)
            except OSError:
                from src.services.search_preset_storage import logger

                logger.warning("Failed to remove preset reference image %s", ref_path)


def _remove_preset_assets(preset: dict, config=None) -> None:
    preset_id = str(preset.get("id", "") or "").strip()
    if preset_id:
        invalidate_all_preset_query_caches(preset_id, config=config)
    _remove_preset_reference_files(preset, config=config)


def _validate_mixed_content(query: str, source_image_paths) -> None:
    query = str(query or "").strip()
    image_paths = [str(path or "").strip() for path in (source_image_paths or []) if str(path or "").strip()]
    if not query and not image_paths:
        raise ValueError("Preset requires query text and/or at least one reference image")


def create_preset(
    *,
    name: str,
    query: str = "",
    source_image_paths=None,
    library_paths=None,
    video_paths=None,
    mode: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    fusion: dict | None = None,
    ui: dict | None = None,
    config=None,
) -> dict:
    query = str(query or "").strip()
    image_paths = [str(path or "").strip() for path in (source_image_paths or []) if str(path or "").strip()]
    _validate_mixed_content(query, image_paths)
    preset_id = uuid.uuid4().hex[:12]
    now = _now_iso()
    ref_files = _copy_reference_images(image_paths, preset_id, config=config)
    preset = normalize_preset_record(
        {
            "id": preset_id,
            "type": PRESET_TYPE_MIXED,
            "name": _sanitize_preset_name(name),
            "query": query,
            "ref_files": ref_files,
            "fusion": normalize_fusion(fusion),
            "library_paths": list(library_paths or []),
            "video_paths": list(video_paths or []),
            "mode": mode,
            "top_k": top_k,
            "min_score": min_score,
            "ui": dict(ui or {}),
            "created_at": now,
            "updated_at": now,
        }
    )
    if not preset:
        raise RuntimeError("Failed to normalize preset record")
    document = load_presets_document(config=config)
    document.setdefault("presets", []).append(preset)
    save_presets_document(document, config=config)
    resolve_preset_query_vector(preset, config=config, force_refresh=True)
    return dict(preset)


def update_preset(
    preset_id: str,
    *,
    name: str | None = None,
    query: str | None = None,
    source_image_paths=None,
    replace_reference_images: bool = False,
    library_paths=None,
    video_paths=None,
    mode: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    fusion: dict | None = None,
    ui: dict | None = None,
    config=None,
) -> dict:
    preset_id = str(preset_id or "").strip()
    if not preset_id:
        raise ValueError("Preset id is required")
    document = load_presets_document(config=config)
    presets = document.get("presets", [])
    updated = None
    for index, item in enumerate(presets):
        if str(item.get("id", "") or "").strip() != preset_id:
            continue
        current = normalize_preset_record(item) or {}
        if name is not None:
            current["name"] = _sanitize_preset_name(name)
        if query is not None:
            current["query"] = str(query or "").strip()
        if fusion is not None:
            current["fusion"] = normalize_fusion(fusion)
        if source_image_paths is not None:
            new_paths = [str(path or "").strip() for path in source_image_paths if str(path or "").strip()]
            if replace_reference_images:
                existing_paths = resolve_preset_ref_paths(current, config=config)
                if _same_reference_paths(existing_paths, new_paths):
                    pass
                else:
                    _remove_preset_reference_files(current, config=config)
                    current["ref_files"] = _copy_reference_images(new_paths, preset_id, config=config)
            elif new_paths:
                start_index = len(current.get("ref_files") or [])
                appended = []
                for offset, path in enumerate(new_paths):
                    appended.append(_copy_reference_image(path, preset_id, start_index + offset, config=config))
                current["ref_files"] = list(current.get("ref_files") or []) + appended
        if library_paths is not None:
            current["library_paths"] = [str(path or "").strip() for path in library_paths if str(path or "").strip()]
        if video_paths is not None:
            current["video_paths"] = [str(path or "").strip() for path in video_paths if str(path or "").strip()]
        if mode is not None:
            current["mode"] = str(mode or "").strip().lower() or None
        if top_k is not None:
            current["top_k"] = int(top_k)
        if min_score is not None:
            current["min_score"] = float(min_score)
        if ui is not None:
            current["ui"] = dict(ui)
        if not preset_has_content(current):
            raise ValueError("Preset requires query text and/or at least one reference image")
        current["updated_at"] = _now_iso()
        updated = normalize_preset_record(current)
        if not updated:
            raise RuntimeError("Failed to normalize updated preset")
        presets[index] = updated
        break
    if updated is None:
        raise KeyError(preset_id)
    save_presets_document(document, config=config)
    invalidate_all_preset_query_caches(preset_id, config=config)
    resolve_preset_query_vector(updated, config=config, force_refresh=True)
    return dict(updated)


def delete_preset(preset_id: str, config=None) -> bool:
    preset_id = str(preset_id or "").strip()
    if not preset_id:
        return False
    document = load_presets_document(config=config)
    presets = document.get("presets", [])
    kept = []
    removed = None
    for item in presets:
        if str(item.get("id", "") or "").strip() == preset_id:
            removed = normalize_preset_record(item)
            continue
        kept.append(item)
    if removed is None:
        return False
    _remove_preset_assets(removed, config=config)
    document["presets"] = kept
    if preset_id in BUILTIN_SEARCH_PRESET_IDS:
        suppressed = _suppressed_builtin_ids(document)
        suppressed.add(preset_id)
        document["suppressed_builtin_ids"] = sorted(suppressed)
    save_presets_document(document, config=config)
    return True
