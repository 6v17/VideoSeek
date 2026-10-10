"""Recap evidence pack build and dialogue cue / speaker helpers.

`recap_service` re-exports `build_recap_pack` so tests can still patch it
(and `compact_ocr_cues`) on the runner module.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.app.config import load_config
from src.services.recap_constants import RECAP_OCR_LIMIT
from src.services.recap_motion import (
    apply_recap_skip_marks,
    compact_index_chunks,
    compact_motion_chunks,
    overlay_motion_captions,
)
from src.services.understanding_resource_service import UNDERSTANDING_MODE_MOTION


def _rs():
    from src.services import recap_service as runner

    return runner


def build_recap_pack(video_id: str, *, config=None) -> dict[str, Any]:
    from src.services.indexing_service import load_video_chunks_by_id
    from src.services.understanding_service import (
        load_evidence_bundle,
        resolve_current_media_path,
        resolve_video_context,
    )

    cfg = config if config is not None else load_config()
    evidence = load_evidence_bundle(video_id, config=cfg, mode=UNDERSTANDING_MODE_MOTION) or {}
    video = dict(evidence.get("video") or {})
    duration = float(video.get("duration_sec") or 0.0)
    stored = str(video.get("video_path") or "")
    video_path = resolve_current_media_path(video_id, stored=stored, config=cfg)
    if not duration or not video_path:
        try:
            context = resolve_video_context(video_id, config=cfg, probe_duration=not duration)
        except Exception as exc:
            from src.app.logging_utils import note_swallowed

            note_swallowed(exc, "src/services/recap_pack.py:video_context")
            context = {}
        if not video_path:
            video_path = str(context.get("video_path") or "")
        if not duration:
            duration = float(context.get("duration_sec") or 0.0)
    # Via runner so tests can patch ``recap_service.compact_ocr_cues``.
    ocr = _rs().compact_ocr_cues(video_id, config=cfg, limit=RECAP_OCR_LIMIT)
    ensure_recap_dialogue_cues(ocr)
    index_rows = compact_index_chunks(load_video_chunks_by_id(video_id, cfg))
    motion_rows = compact_motion_chunks(evidence) if evidence else []
    if index_rows:
        chunks = overlay_motion_captions(index_rows, motion_rows)
    else:
        chunks = motion_rows
    if not chunks:
        raise RuntimeError("没有可用分段。请先索引该视频。")
    chunks = apply_recap_skip_marks(chunks, ocr, duration)
    return {
        "video_id": video_id,
        "video_path": video_path,
        "duration_sec": duration,
        "chunks": chunks,
        "ocr": ocr,
        "ocr_source": "asr",
        "people": people_from_dialogue_speakers(ocr),
    }

def list_speech_dialogue_cues(video_id: str, *, config=None) -> list[dict[str, Any]]:
    """Full ASR rows for the understanding table, including speaker labels."""
    from src.services.asr_index_service import is_hardsub_ocr_source
    from src.storage.dialogue_transcript_store import load_dialogue_transcript

    payload = load_dialogue_transcript(str(video_id or "").strip(), config=config) or {}
    default_source = str(payload.get("asr_source") or "").strip()
    cues: list[dict[str, Any]] = []
    for index, row in enumerate(payload.get("segments") or []):
        if not isinstance(row, Mapping):
            continue
        source = str(row.get("asr_source") or default_source or "").strip()
        if not source or is_hardsub_ocr_source(source):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            seg_index = int(row.get("seg_index", index))
        except (TypeError, ValueError):
            seg_index = index
        start = float(row.get("start") or 0.0)
        end = float(row.get("end") or start)
        cues.append(
            {
                "seg_index": seg_index,
                "start": start,
                "end": end,
                "text": text,
                "asr_source": source,
                "speaker": str(row.get("speaker") or "").strip()[:40],
            }
        )
    return cues

def recap_dialogue_status(video_id: str, *, config=None) -> dict[str, Any]:
    vid = str(video_id or "").strip()
    if not vid:
        return {"ready": False, "count": 0, "source": ""}
    from src.services.asr_index_service import is_hardsub_ocr_source
    from src.storage.dialogue_transcript_store import list_dialogue_transcript_summaries

    rows = list_dialogue_transcript_summaries(config=config, video_ids=[vid])
    if not rows:
        return {"ready": False, "count": 0, "source": ""}
    source = str(rows[0].get("asr_source") or "").strip()
    if not source or is_hardsub_ocr_source(source):
        return {"ready": False, "count": 0, "source": source}
    count = int(rows[0].get("segment_count") or 0)
    return {"ready": count > 0, "count": count, "source": source}

def people_from_dialogue_speakers(cues: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Seed the recap people table from ASR speakers (named + clustered 声线)."""
    from src.storage.dialogue_transcript_store import is_auto_speaker_label

    named: list[dict[str, Any]] = []
    auto: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in cues or []:
        label = str(row.get("speaker") or "").strip()[:40]
        if not label or label in seen:
            continue
        seen.add(label)
        entry = {
            "id": f"s{len(seen)}",
            "label": label,
            "look": "声纹聚类" if is_auto_speaker_label(label) else "对白说话人",
        }
        if is_auto_speaker_label(label):
            auto.append(entry)
        else:
            named.append(entry)
        if len(named) + len(auto) >= 16:
            break
    # Prefer real names first; keep 声线N so plan/VO can tell talkers apart.
    return [*named, *auto][:16]

def ensure_recap_dialogue_cues(cues: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    items = list(cues or [])
    if not items:
        raise RuntimeError(
            "没有语音对白。请先在理解页提取语音 ASR。"
        )
    return items

def recap_speaker_stats(cues: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    from src.storage.dialogue_transcript_store import is_auto_speaker_label

    blank = 0
    auto = 0
    named = 0
    for row in cues or []:
        label = str(row.get("speaker") or "").strip()
        if not label:
            blank += 1
        elif is_auto_speaker_label(label):
            auto += 1
        else:
            named += 1
    unnamed = blank + auto
    return {
        "blank": blank,
        "auto": auto,
        "named": named,
        "unnamed": unnamed,
        "needs_naming": unnamed > 0,
    }
