from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.core.understanding.pipeline import UnderstandingPipeline
from src.core.understanding.base import UnderstandingStoppedError
from src.domain.evidence_bundle import (
    EVIDENCE_BUNDLE_SCHEMA_VERSION,
    evidence_bundle_to_dict,
    validate_evidence_bundle,
)
from src.services.understanding_paths import get_evidence_path, get_evidence_root, get_evidence_videos_dir
from src.services.understanding_resource_service import (
    get_active_understanding_profile,
    get_understanding_resource_status,
    load_profile_manifest,
)
from src.storage.asset_store import load_model_metadata
from src.storage.config_store import get_active_embedding_spec, get_active_model_profile
from src.utils import canonicalize_library_path, format_timecode_range, get_video_duration_seconds

logger = get_logger("understanding.service")


class UnderstandingGenerationError(RuntimeError):
    """Raised when evidence generation cannot proceed."""


def _atomic_write_json(path: str, payload: Mapping[str, Any]) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_video_context(video_id: str, config=None) -> dict[str, Any]:
    from src.services.search_scope import iter_indexed_video_entries

    video_text = str(video_id or "").strip()
    if not video_text:
        raise UnderstandingGenerationError("video_id is required")

    cfg = dict(config or load_config())
    meta = load_model_metadata(config=cfg)
    for library_path, library_data in (meta.get("libraries") or {}).items():
        if not isinstance(library_data, dict):
            continue
        files = library_data.get("files") or {}
        if not isinstance(files, dict):
            continue
        root = os.path.normpath(str(library_path))
        for rel_path, info in files.items():
            if not isinstance(info, dict):
                continue
            if str(info.get("vid", "") or "").strip() != video_text:
                continue
            video_path = os.path.normpath(os.path.join(root, str(rel_path)))
            duration_sec = get_video_duration_seconds(video_path)
            return {
                "video_id": video_text,
                "video_path": video_path,
                "video_rel_path": str(rel_path),
                "library_path": root,
                "duration_sec": float(duration_sec) if duration_sec is not None else None,
                "source_exists": os.path.isfile(video_path),
                "asset_state": str(info.get("asset_state", "") or "").strip().lower(),
            }

    for abs_path, candidate_id, info in iter_indexed_video_entries(meta):
        if candidate_id != video_text:
            continue
        duration_sec = get_video_duration_seconds(abs_path)
        library_path = ""
        video_rel_path = ""
        for root, library_data in (meta.get("libraries") or {}).items():
            files = (library_data or {}).get("files") or {}
            for rel_path, file_info in files.items():
                if str((file_info or {}).get("vid", "") or "").strip() == video_text:
                    library_path = os.path.normpath(str(root))
                    video_rel_path = str(rel_path)
                    break
            if library_path:
                break
        return {
            "video_id": video_text,
            "video_path": os.path.normpath(abs_path),
            "video_rel_path": video_rel_path,
            "library_path": library_path,
            "duration_sec": float(duration_sec) if duration_sec is not None else None,
            "source_exists": os.path.isfile(abs_path),
            "asset_state": str(info.get("asset_state", "") or "").strip().lower(),
        }

    raise UnderstandingGenerationError(f"Video not found in library metadata: {video_text}")


def list_ready_video_entries(*, library_path: str | None = None, config=None) -> list[dict[str, Any]]:
    from src.services.library_service import list_local_vector_details

    cfg = dict(config or load_config())
    details = list_local_vector_details(validate_contents=False)
    entries = list(details.get("entries") or [])
    target_library = canonicalize_library_path(library_path) if library_path else ""
    ready_entries: list[dict[str, Any]] = []
    for entry in entries:
        if str(entry.get("asset_state", "") or "").strip().lower() != "ready":
            continue
        if not bool(entry.get("source_exists", False)):
            continue
        entry_library = canonicalize_library_path(str(entry.get("library_path", "") or ""))
        if target_library and entry_library != target_library:
            continue
        video_path = os.path.normpath(os.path.join(entry_library, str(entry.get("video_rel_path", "") or "")))
        ready_entries.append(
            {
                **dict(entry),
                "video_path": video_path,
            }
        )
    return ready_entries


def _extract_chunk_caption_text(chunk_payload: Mapping[str, Any]) -> str:
    if not isinstance(chunk_payload, dict):
        return ""
    vision = dict(dict(chunk_payload.get("evidence") or {}).get("vision") or {})
    return str(dict(vision.get("image_caption") or {}).get("text", "") or "").strip()


def _build_segment_descriptions_for_summary(chunk_payloads: list[Mapping[str, Any]]) -> str:
    lines: list[str] = []
    for index, chunk in enumerate(chunk_payloads):
        caption = _extract_chunk_caption_text(chunk)
        if not caption:
            continue
        start_sec = float(chunk.get("start_sec", 0.0))
        end_sec = float(chunk.get("end_sec", start_sec))
        time_range = format_timecode_range(start_sec, end_sec)
        lines.append(f"{index + 1}. [{time_range}] {caption}")
    return "\n".join(lines)


def generate_video_summary_from_chunks(
    chunk_payloads: list[Mapping[str, Any]],
    *,
    config=None,
    should_stop_callback=None,
) -> dict[str, str] | None:
    segment_text = _build_segment_descriptions_for_summary(chunk_payloads)
    if not segment_text.strip():
        return None

    from src.core.understanding.base import UnderstandingStoppedError
    from src.core.understanding.components.remote_vl_caption import call_remote_vlm_text_completion
    from src.services.understanding_resource_service import (
        get_remote_vlm_settings,
        get_video_summary_prompt_for_language,
        normalize_caption_language,
    )

    cfg = dict(config or load_config())
    remote_vlm = get_remote_vlm_settings(cfg)
    language = normalize_caption_language(remote_vlm.get("caption_language", "zh"))
    instruction = get_video_summary_prompt_for_language(language)
    prompt = f"{instruction}\n\n{segment_text}"
    try:
        summary_text = call_remote_vlm_text_completion(
            prompt=prompt,
            config=cfg,
            max_tokens=384,
            should_stop_callback=should_stop_callback,
        )
    except UnderstandingStoppedError:
        raise
    except Exception as exc:
        logger.warning("Video summary generation failed: %s", exc)
        return None

    summary_text = str(summary_text or "").strip()
    if not summary_text:
        return None
    return {"text": summary_text, "source": "remote_vlm"}


def build_evidence_bundle_payload(
    *,
    video_context: Mapping[str, Any],
    chunks: list[Mapping[str, Any]],
    profile_manifest: Mapping[str, Any],
    profile_id: str,
    config=None,
    should_stop_callback=None,
    chunk_completed_callback=None,
) -> dict[str, Any]:
    cfg = dict(config or load_config())
    pipeline = UnderstandingPipeline(profile_manifest, config=cfg)
    try:
        chunk_payloads = pipeline.run_video_chunks(
            video_path=str(video_context["video_path"]),
            chunks=chunks,
            should_stop_callback=should_stop_callback,
            chunk_completed_callback=chunk_completed_callback,
        )
    finally:
        pipeline.close()

    if should_stop_callback and should_stop_callback():
        raise UnderstandingStoppedError("Evidence generation stopped by user")

    summary_payload = None
    if "image_caption" in pipeline.component_map():
        try:
            summary_payload = generate_video_summary_from_chunks(
                chunk_payloads,
                config=cfg,
                should_stop_callback=should_stop_callback,
            )
        except UnderstandingStoppedError:
            raise

    search_profile = get_active_model_profile(config=cfg)
    embedding_spec = get_active_embedding_spec(config=cfg)
    runtime = dict(search_profile.get("runtime") or {})
    search_variant = str(runtime.get("model_variant", "") or search_profile.get("model_variant", "") or "").strip()
    if not search_variant:
        search_variant = "vit-base-patch32"

    payload = {
        "schema_version": EVIDENCE_BUNDLE_SCHEMA_VERSION,
        "video": {
            "video_id": str(video_context["video_id"]),
            "video_path": str(video_context["video_path"]),
            "video_rel_path": str(video_context.get("video_rel_path", "") or ""),
            "library_path": str(video_context.get("library_path", "") or ""),
            "duration_sec": video_context.get("duration_sec"),
            "source_exists": bool(video_context.get("source_exists", True)),
        },
        "provenance": {
            "understanding_profile_id": profile_id,
            "components": pipeline.component_map(),
            "chunk_source": {
                "search_profile_id": str(embedding_spec.get("model_id", "") or search_profile.get("id", "") or ""),
                "search_provider": str(search_profile.get("provider", "") or embedding_spec.get("provider", "") or ""),
                "search_variant": search_variant,
            },
            "keyframe_strategy": pipeline.keyframe_strategy,
            "generated_at": _utc_timestamp(),
        },
        "chunks": chunk_payloads,
    }
    if summary_payload:
        payload["summary"] = summary_payload
    validate_evidence_bundle(payload)
    return payload


def write_evidence_bundle(video_id: str, payload: Mapping[str, Any], *, config=None) -> str:
    path = get_evidence_path(video_id, config=config)
    bundle = validate_evidence_bundle(payload)
    _atomic_write_json(path, evidence_bundle_to_dict(bundle))
    return path


def load_evidence_bundle(video_id: str, *, config=None) -> dict[str, Any] | None:
    path = get_evidence_path(video_id, config=config)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def generate_evidence_for_video(
    video_id: str,
    *,
    config=None,
    model_dir: str | None = None,
    should_stop_callback=None,
    chunk_completed_callback=None,
) -> dict[str, Any]:
    from src.services.indexing_service import load_video_chunks_by_id

    cfg = dict(config or load_config())
    status = get_understanding_resource_status(config=cfg, model_dir=model_dir)
    if not status.get("understanding_ready"):
        missing = ", ".join(status.get("missing_components") or [])
        raise UnderstandingGenerationError(
            f"Understanding resources are not ready (missing: {missing or 'unknown'})"
        )

    video_context = resolve_video_context(video_id, config=cfg)
    if not video_context.get("source_exists"):
        raise UnderstandingGenerationError(f"Video source file is missing: {video_context.get('video_path')}")

    chunks = load_video_chunks_by_id(video_id, cfg)
    if not chunks:
        raise UnderstandingGenerationError(f"No semantic chunks available for video: {video_id}")

    profile = get_active_understanding_profile(config=cfg)
    profile_id = str(profile.get("id", "") or "").strip()
    profile_manifest = dict(profile.get("manifest") or load_profile_manifest(profile_id, model_dir=model_dir))

    payload = build_evidence_bundle_payload(
        video_context=video_context,
        chunks=chunks,
        profile_manifest=profile_manifest,
        profile_id=profile_id,
        config=cfg,
        should_stop_callback=should_stop_callback,
        chunk_completed_callback=chunk_completed_callback,
    )
    output_path = write_evidence_bundle(video_id, payload, config=cfg)
    return {
        "video_id": video_id,
        "evidence_path": output_path,
        "chunk_count": len(payload.get("chunks") or []),
        "understanding_profile_id": profile_id,
    }


def generate_evidence_batch(
    *,
    target_lib: str | None = None,
    config=None,
    model_dir: str | None = None,
    progress_callback=None,
    should_stop_callback=None,
) -> dict[str, Any]:
    from src.services.library_service import list_libraries

    cfg = dict(config or load_config())
    status = get_understanding_resource_status(config=cfg, model_dir=model_dir)
    if not status.get("understanding_ready"):
        missing = ", ".join(status.get("missing_components") or [])
        raise UnderstandingGenerationError(
            f"Understanding resources are not ready (missing: {missing or 'unknown'})"
        )

    if target_lib:
        library_paths = [canonicalize_library_path(target_lib)]
    else:
        library_paths = sorted(str(path) for path in list_libraries().keys())

    jobs: list[tuple[str, dict[str, Any]]] = []
    for library_path in library_paths:
        for entry in list_ready_video_entries(library_path=library_path, config=cfg):
            jobs.append((library_path, entry))

    generated: list[dict[str, Any]] = []
    errors: list[str] = []
    stopped = False
    total = len(jobs)

    for index, (_library_path, entry) in enumerate(jobs):
        if should_stop_callback and should_stop_callback():
            stopped = True
            break
        video_id = str(entry.get("video_id", "") or "").strip()
        if not video_id:
            continue
        if progress_callback:
            progress = min(99, int((index / total) * 100)) if total else 0
            progress_callback(progress, video_id, index + 1, total)
        try:
            generated.append(
                generate_evidence_for_video(
                    video_id,
                    config=cfg,
                    model_dir=model_dir,
                    should_stop_callback=should_stop_callback,
                )
            )
        except UnderstandingStoppedError:
            stopped = True
            break
        except Exception as exc:
            logger.warning("Evidence generation failed for %s: %s", video_id, exc)
            errors.append(f"{video_id}: {exc}")

    if progress_callback and not stopped:
        progress_callback(100, "", total, total)

    return {
        "target_lib": canonicalize_library_path(target_lib) if target_lib else "",
        "library_paths": library_paths,
        "generated": generated,
        "errors": errors,
        "requested_count": total,
        "generated_count": len(generated),
        "stopped": stopped,
    }


def generate_evidence_for_library(
    library_path: str,
    *,
    config=None,
    model_dir: str | None = None,
    progress_callback=None,
    should_stop_callback=None,
) -> dict[str, Any]:
    result = generate_evidence_batch(
        target_lib=library_path,
        config=config,
        model_dir=model_dir,
        progress_callback=progress_callback,
        should_stop_callback=should_stop_callback,
    )
    return {
        "library_path": canonicalize_library_path(library_path),
        "generated": result.get("generated") or [],
        "errors": result.get("errors") or [],
        "requested_count": int(result.get("requested_count", 0) or 0),
        "generated_count": int(result.get("generated_count", 0) or 0),
        "stopped": bool(result.get("stopped")),
    }


def _component_short_name(component_id: str) -> str:
    text = str(component_id or "").strip()
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def _read_evidence_file_summary(evidence_path: str) -> dict[str, Any]:
    if not os.path.isfile(evidence_path):
        return {}
    try:
        with open(evidence_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {"load_error": True}

    if not isinstance(payload, dict):
        return {"load_error": True}

    provenance = dict(payload.get("provenance") or {})
    chunk_source = dict(provenance.get("chunk_source") or {})
    components = dict(provenance.get("components") or {})
    video = dict(payload.get("video") or {})
    yolo_id = str(components.get("object_detection", "") or "").strip()
    caption_id = str(components.get("image_caption", "") or "").strip()
    other_ids = [
        str(value).strip()
        for key, value in components.items()
        if key not in {"object_detection", "image_caption"} and str(value or "").strip()
    ]
    clip_model = str(chunk_source.get("search_variant", "") or "").strip()
    if not clip_model:
        clip_model = str(chunk_source.get("search_profile_id", "") or "").strip()

    video_path = str(video.get("video_path", "") or "").strip()
    source_exists = video.get("source_exists")
    if source_exists is None and video_path:
        source_exists = os.path.isfile(video_path)

    return {
        "video_id": str(video.get("video_id", "") or "").strip(),
        "video_path": video_path,
        "library_path": str(video.get("library_path", "") or "").strip(),
        "video_rel_path": str(video.get("video_rel_path", "") or "").strip(),
        "source_exists": bool(source_exists),
        "clip_model": clip_model,
        "search_provider": str(chunk_source.get("search_provider", "") or "").strip(),
        "yolo_model": _component_short_name(yolo_id),
        "caption_model": _component_short_name(caption_id),
        "other_models": ", ".join(_component_short_name(item) or item for item in other_ids),
        "understanding_profile_id": str(provenance.get("understanding_profile_id", "") or "").strip(),
        "generated_at": str(provenance.get("generated_at", "") or "").strip(),
        "chunk_count": len(payload.get("chunks") or []),
        "load_error": False,
    }


def list_local_evidence_details(*, config=None) -> dict[str, Any]:
    from src.services.library_service import list_local_vector_details

    cfg = dict(config or load_config())
    evidence_dir = os.path.normpath(get_evidence_videos_dir(config=cfg))
    library_by_video_id: dict[str, dict[str, Any]] = {}
    for item in list_local_vector_details(validate_contents=False).get("entries") or []:
        video_id = str(item.get("video_id", "") or "").strip()
        if video_id:
            library_by_video_id[video_id] = dict(item)

    entries: list[dict[str, Any]] = []
    if os.path.isdir(evidence_dir):
        for name in sorted(os.listdir(evidence_dir)):
            if not str(name).lower().endswith(".json"):
                continue
            evidence_file = os.path.normpath(os.path.join(evidence_dir, name))
            if not os.path.isfile(evidence_file):
                continue

            video_id = os.path.splitext(name)[0]
            summary = _read_evidence_file_summary(evidence_file)
            if not video_id:
                video_id = str(summary.get("video_id", "") or "").strip()
            library_item = library_by_video_id.get(video_id, {})

            library_path = str(summary.get("library_path", "") or library_item.get("library_path", "") or "")
            video_rel_path = str(summary.get("video_rel_path", "") or library_item.get("video_rel_path", "") or "")
            source_exists = summary.get("source_exists")
            if source_exists is False and library_item:
                source_exists = bool(library_item.get("source_exists", False))
            elif summary.get("load_error"):
                source_exists = bool(library_item.get("source_exists", False))
            else:
                source_exists = bool(source_exists)

            if summary.get("load_error"):
                evidence_state = "invalid"
            else:
                evidence_state = "ready"

            entries.append(
                {
                    "library_path": library_path,
                    "video_rel_path": video_rel_path,
                    "video_id": video_id,
                    "source_exists": source_exists,
                    "asset_state": str(library_item.get("asset_state", "") or "").strip().lower(),
                    "evidence_file": evidence_file,
                    "evidence_exists": True,
                    "evidence_state": evidence_state,
                    "clip_model": str(summary.get("clip_model", "") or ""),
                    "search_provider": str(summary.get("search_provider", "") or ""),
                    "yolo_model": str(summary.get("yolo_model", "") or ""),
                    "caption_model": str(summary.get("caption_model", "") or ""),
                    "other_models": str(summary.get("other_models", "") or ""),
                    "understanding_profile_id": str(summary.get("understanding_profile_id", "") or ""),
                    "generated_at": str(summary.get("generated_at", "") or ""),
                    "chunk_count": int(summary.get("chunk_count", 0) or 0),
                }
            )

    count = len(entries)
    return {
        "evidence_dir": evidence_dir,
        "entries": entries,
        "total_entries": count,
        "evidence_count": count,
    }


def _evidence_file_paths(video_id: str, *, config=None) -> list[str]:
    base_path = get_evidence_path(video_id, config=config)
    paths = [base_path, f"{base_path}.tmp"]
    return [os.path.normpath(path) for path in paths]


def _remove_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    removed: list[str] = []
    errors: list[str] = []
    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        try:
            os.remove(path)
            removed.append(path)
        except Exception as exc:
            logger.warning("Failed to delete evidence path %s: %s", path, exc)
            errors.append(f"{path}: {exc}")
    return removed, errors


def delete_evidence_for_video(video_id: str, *, config=None) -> bool:
    removed, _errors = _remove_paths(_evidence_file_paths(video_id, config=config))
    return bool(removed)


def delete_evidence_for_videos(video_ids: list[str], *, config=None) -> dict[str, Any]:
    deleted: list[str] = []
    errors: list[str] = []
    for video_id in video_ids:
        video_text = str(video_id or "").strip()
        if not video_text:
            continue
        removed, item_errors = _remove_paths(_evidence_file_paths(video_text, config=config))
        errors.extend(item_errors)
        if removed:
            deleted.append(video_text)
    return {
        "deleted": deleted,
        "errors": errors,
        "deleted_count": len(deleted),
    }


def clear_all_evidence(*, config=None) -> dict[str, Any]:
    cfg = dict(config or load_config())
    evidence_root = os.path.normpath(get_evidence_root(config=cfg))
    evidence_dir = os.path.normpath(get_evidence_videos_dir(config=cfg))
    deleted: list[str] = []
    errors: list[str] = []

    targets: list[str] = []
    for folder in (evidence_dir, evidence_root):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                targets.append(path)

    removed, errors = _remove_paths(targets)
    deleted.extend(os.path.basename(path) for path in removed)
    return {
        "deleted": deleted,
        "errors": errors,
        "deleted_count": len(removed),
    }
