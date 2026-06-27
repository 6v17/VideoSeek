"""Search preset record normalization and listing."""

from __future__ import annotations

from src.services.search_preset_constants import (
    BUILTIN_SEARCH_PRESETS,
    DEFAULT_FUSION,
    PRESET_TYPE_MIXED,
)
from src.services.search_preset_storage import (
    _now_iso,
    _suppressed_builtin_ids,
    load_presets_document,
    save_presets_document,
)


def normalize_fusion(raw) -> dict:
    fusion = dict(DEFAULT_FUSION)
    if isinstance(raw, dict):
        for key in ("text_weight", "image_weight"):
            try:
                fusion[key] = float(raw.get(key, fusion[key]))
            except (TypeError, ValueError):
                pass
    total = float(fusion["text_weight"]) + float(fusion["image_weight"])
    if total <= 0:
        return dict(DEFAULT_FUSION)
    return {
        "text_weight": float(fusion["text_weight"]) / total,
        "image_weight": float(fusion["image_weight"]) / total,
    }


def _collect_ref_files(raw: dict) -> list[str]:
    ref_files = []
    for ref_file in list((raw or {}).get("ref_files") or []):
        normalized = str(ref_file or "").strip()
        if normalized:
            ref_files.append(normalized)
    if ref_files:
        return ref_files
    legacy = str((raw or {}).get("ref_file", "") or "").strip()
    if legacy:
        return [legacy]
    return []


def preset_has_content(preset: dict) -> bool:
    query = str((preset or {}).get("query", "") or "").strip()
    ref_files = _collect_ref_files(preset)
    return bool(query or ref_files)


def normalize_preset_record(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    preset_id = str(raw.get("id", "") or "").strip()
    name = str(raw.get("name", "") or "").strip()
    if not preset_id or not name:
        return None
    library_paths = [
        str(path or "").strip()
        for path in (raw.get("library_paths") or [])
        if str(path or "").strip()
    ]
    video_paths = [
        str(path or "").strip()
        for path in (raw.get("video_paths") or [])
        if str(path or "").strip()
    ]
    ui = raw.get("ui") if isinstance(raw.get("ui"), dict) else {}
    top_k = raw.get("top_k")
    min_score = raw.get("min_score")
    try:
        top_k_value = int(top_k) if top_k is not None else None
    except (TypeError, ValueError):
        top_k_value = None
    try:
        min_score_value = float(min_score) if min_score is not None else None
    except (TypeError, ValueError):
        min_score_value = None
    mode = str(raw.get("mode", "") or "").strip().lower() or None
    if mode not in {None, "frame", "chunk"}:
        mode = None
    preset = {
        "id": preset_id,
        "type": PRESET_TYPE_MIXED,
        "name": name,
        "query": str(raw.get("query", "") or "").strip(),
        "ref_files": _collect_ref_files(raw),
        "fusion": normalize_fusion(raw.get("fusion")),
        "library_paths": library_paths,
        "video_paths": video_paths,
        "mode": mode,
        "top_k": top_k_value,
        "min_score": min_score_value,
        "ui": dict(ui),
        "created_at": str(raw.get("created_at", "") or "").strip(),
        "updated_at": str(raw.get("updated_at", "") or "").strip(),
    }
    if not preset_has_content(preset):
        return None
    return preset


def ensure_builtin_search_presets(config=None) -> int:
    """Insert built-in text presets when their stable ids are missing."""
    document = load_presets_document(config=config)
    presets = list(document.get("presets") or [])
    existing_ids = {
        str(item.get("id", "") or "").strip()
        for item in presets
        if isinstance(item, dict)
    }
    suppressed = _suppressed_builtin_ids(document)
    added = 0
    now = _now_iso()
    for spec in BUILTIN_SEARCH_PRESETS:
        preset_id = str(spec.get("id", "") or "").strip()
        if not preset_id or preset_id in existing_ids or preset_id in suppressed:
            continue
        record = normalize_preset_record(
            {
                "id": preset_id,
                "type": PRESET_TYPE_MIXED,
                "name": str(spec.get("name", "") or "").strip(),
                "query": str(spec.get("query", "") or "").strip(),
                "ref_files": [],
                "fusion": dict(DEFAULT_FUSION),
                "library_paths": [],
                "video_paths": [],
                "mode": None,
                "top_k": None,
                "min_score": None,
                "ui": {},
                "created_at": now,
                "updated_at": now,
            }
        )
        if not record:
            continue
        presets.append(record)
        existing_ids.add(preset_id)
        added += 1
    if added:
        document["presets"] = presets
        save_presets_document(document, config=config)
    return added


def list_presets(config=None) -> list[dict]:
    ensure_builtin_search_presets(config=config)
    document = load_presets_document(config=config)
    presets = []
    for item in document.get("presets", []):
        normalized = normalize_preset_record(item)
        if normalized:
            presets.append(normalized)
    return presets


def get_preset(preset_id: str, config=None) -> dict | None:
    preset_id = str(preset_id or "").strip()
    if not preset_id:
        return None
    for preset in list_presets(config=config):
        if str(preset.get("id", "") or "").strip() == preset_id:
            return dict(preset)
    return None


def describe_preset_content(preset: dict, config=None) -> str:
    from src.services.search_preset_storage import resolve_preset_ref_paths

    preset = dict(preset or {})
    parts = []
    query = str(preset.get("query", "") or "").strip()
    if query:
        parts.append(query)
    ref_count = len(resolve_preset_ref_paths(preset, config=config))
    if ref_count:
        parts.append(f"[{ref_count} image(s)]")
    if query and ref_count:
        fusion = normalize_fusion(preset.get("fusion"))
        text_pct = int(round(float(fusion["text_weight"]) * 100))
        image_pct = 100 - text_pct
        parts.append(f"({text_pct}:{image_pct})")
    return " + ".join(parts) if parts else ""
