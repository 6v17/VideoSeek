"""Build the recap evidence pack (chunks + ASR + people).

``recap_service`` re-exports ``build_recap_pack`` so tests can still patch it
(and ``compact_ocr_cues``) on the runner module.
"""

from __future__ import annotations

from typing import Any

from src.app.config import load_config
from src.services.recap_constants import RECAP_OCR_LIMIT
from src.services.recap_dialogue import (
    ensure_recap_dialogue_cues,
    people_from_dialogue_speakers,
)
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
        except Exception:
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
