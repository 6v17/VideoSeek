"""Producer–consumer OCR pipeline (CLIP-index style overlap).

Reader thread decodes/crops while the main thread runs RapidOCR, via a bounded
``queue.Queue``. Disable with ``VIDEOSEEK_DISABLE_SUBTITLE_OCR_OVERLAP=1``.

Optional micro-batching stacks several ROIs into one OCR call (see
``ocr_batch_fn`` / ``batch_size``). Blank and unchanged subtitle bands are
skipped before OCR so probe density can stay high without burning OCR cost.

Timeline probing may OCR both a top title band and a bottom dialogue band;
fingerprints / cue extension stay per-band so they do not cross-contaminate.
"""

from __future__ import annotations

import os
import queue
import threading
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from src.app.logging_utils import get_logger
from src.core.subtitle_ocr.frame_sample import (
    crop_subtitle_rois,
    iter_frames_at_times,
    roi_changed,
    roi_likely_blank,
)

logger = get_logger("subtitle_ocr.pipeline")

StopCallback = Callable[[], bool]
ProgressCallback = Callable[[float, str], None]
OcrFn = Callable[[np.ndarray], str]
OcrBatchFn = Callable[[Sequence[np.ndarray]], Sequence[str]]

# Fingerprint can miss near-identical layouts with different glyphs; force OCR
# every N consecutive "unchanged" hits so dense timeline probes still catch swaps.
_FORCE_OCR_EVERY_UNCHANGED = 4


def _use_overlap_reader() -> bool:
    v = os.environ.get("VIDEOSEEK_DISABLE_SUBTITLE_OCR_OVERLAP", "").strip().lower()
    return v not in {"1", "true", "yes"}


def _drain_queue(frame_queue: queue.Queue) -> None:
    while True:
        try:
            frame_queue.get_nowait()
        except queue.Empty:
            return


def _reader_loop(
    video_path: str,
    times: Sequence[float],
    frame_queue: queue.Queue,
    stop_event: threading.Event,
    reader_error: list[BaseException],
    include_top_band: bool,
) -> None:
    """Decode + ROI crop (+ blank skip) while OCR consumes on the other side."""
    try:
        for index, (time_sec, frame) in enumerate(iter_frames_at_times(video_path, times)):
            if stop_event.is_set():
                return
            bands = crop_subtitle_rois(frame, include_top=include_top_band)
            if not bands:
                item: tuple[Any, ...] = ("skip", index, float(time_sec), "bottom")
                items = [item]
            else:
                items = []
                for band, roi in bands:
                    if roi_likely_blank(roi):
                        items.append(("skip", index, float(time_sec), str(band)))
                    else:
                        items.append(
                            ("frame", index, float(time_sec), str(band), np.ascontiguousarray(roi))
                        )
            for item in items:
                while True:
                    if stop_event.is_set():
                        return
                    try:
                        frame_queue.put(item, timeout=0.25)
                        break
                    except queue.Full:
                        continue
    except Exception as exc:
        logger.exception("Subtitle OCR frame reader failed for %s", video_path)
        reader_error.append(exc)
    finally:
        try:
            frame_queue.put(None, timeout=30.0)
        except queue.Full:
            logger.warning("Subtitle OCR frame queue full while sending end sentinel")


def collect_ocr_observations(
    video_path: str,
    times: Sequence[float],
    *,
    ocr_fn: OcrFn,
    ocr_batch_fn: OcrBatchFn | None = None,
    batch_size: int = 1,
    duration: float = 0.0,
    asr_source: str = "",
    stop_callback: StopCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_base: float = 0.20,
    progress_span: float = 0.70,
    queue_size: int = 12,
    stats_out: dict[str, int] | None = None,
    include_top_band: bool = False,
) -> list[dict[str, Any]]:
    """Decode/OCR with optional overlap + ROI batching; return raw observations.

    Non-blank ROIs that look unchanged vs the last OCR'd plate *on the same
    band* are skipped, and that band's previous cue end time is extended.
    """
    ordered = list(times)
    total = max(1, len(ordered))
    observations: list[dict[str, Any]] = []
    # Per-band gates so top titles and bottom dialogue do not share state.
    band_state: dict[str, dict[str, Any]] = {}
    batch_n = max(1, int(batch_size or 1))
    use_batch = batch_n > 1 and ocr_batch_fn is not None
    pending: list[tuple[float, np.ndarray, str]] = []
    stats = {
        "probed": 0,
        "ocr_calls": 0,
        "blank_skips": 0,
        "unchanged_skips": 0,
    }
    last_progress_index = -1

    def _state_for(band: str) -> dict[str, Any]:
        key = str(band or "bottom")
        st = band_state.get(key)
        if st is None:
            st = {
                "fingerprint": None,
                "unchanged_streak": 0,
                "last_text": "",
                "last_idx": -1,
            }
            band_state[key] = st
        return st

    def _stopped() -> bool:
        return bool(stop_callback and stop_callback())

    def _emit_progress(done: int) -> None:
        if not progress_callback:
            return
        ratio = min(1.0, max(0.0, float(done) / float(total)))
        progress_callback(progress_base + progress_span * ratio, f"subtitle_ocr|{done}|{total}")

    def _note_frame(index: int) -> None:
        nonlocal last_progress_index
        if index == last_progress_index:
            return
        last_progress_index = index
        stats["probed"] += 1
        _emit_progress(index + 1)

    def _extend_band_observation(time_sec: float, band: str) -> None:
        st = _state_for(band)
        idx = int(st["last_idx"])
        if idx < 0 or idx >= len(observations):
            return
        observations[idx]["end"] = min(
            duration if duration > 0 else time_sec + 1.2,
            max(float(observations[idx]["end"]), time_sec + 1.0),
        )

    def _accept_text(time_sec: float, text: str, band: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        st = _state_for(band)
        idx = int(st["last_idx"])
        if text == str(st["last_text"] or "") and 0 <= idx < len(observations):
            observations[idx]["end"] = min(
                duration if duration > 0 else time_sec + 1.2,
                max(float(observations[idx]["end"]), time_sec + 1.0),
            )
            return
        st["last_text"] = text
        observations.append(
            {
                "start": max(0.0, time_sec - 0.3),
                "end": min(duration if duration > 0 else time_sec + 1.2, time_sec + 1.2),
                "text": text,
                "language": "",
                "asr_source": asr_source,
            }
        )
        st["last_idx"] = len(observations) - 1

    def _active_batch_n() -> int:
        if not use_batch:
            return 1
        try:
            from src.core.subtitle_ocr.rapidocr_engine import _effective_prefer_gpu

            # After GPU→CPU sticky fallback, flush one ROI at a time so progress moves.
            if not _effective_prefer_gpu(True):
                return 1
        except Exception:
            pass
        return batch_n

    def _flush_pending() -> None:
        if not pending:
            return
        if use_batch and _active_batch_n() > 1:
            rois = [roi for _t, roi, _band in pending]
            lines = list(ocr_batch_fn(rois) or [])
            if len(lines) < len(pending):
                lines.extend([""] * (len(pending) - len(lines)))
            stats["ocr_calls"] += len(pending)
            for (time_sec, _roi, band), text in zip(pending, lines):
                _accept_text(time_sec, text, band)
        else:
            for time_sec, roi, band in pending:
                stats["ocr_calls"] += 1
                _accept_text(time_sec, ocr_fn(roi), band)
        pending.clear()

    def _consider_roi(time_sec: float, roi: np.ndarray, band: str) -> None:
        st = _state_for(band)
        changed, fingerprint = roi_changed(roi, st["fingerprint"])
        if not changed:
            st["unchanged_streak"] = int(st["unchanged_streak"]) + 1
            if int(st["unchanged_streak"]) < _FORCE_OCR_EVERY_UNCHANGED:
                stats["unchanged_skips"] += 1
                _extend_band_observation(time_sec, band)
                return
            # Sticky plate: still OCR periodically in case glyphs swapped under the gate.
        st["unchanged_streak"] = 0
        st["fingerprint"] = fingerprint
        pending.append((float(time_sec), roi, str(band)))
        if len(pending) >= _active_batch_n():
            _flush_pending()

    if progress_callback:
        progress_callback(progress_base, f"subtitle_ocr|0|{total}")

    if not ordered:
        if stats_out is not None:
            stats_out.update(stats)
        return observations

    if use_batch:
        logger.info("Subtitle OCR ROI batch size=%d", batch_n)
    if include_top_band:
        logger.info("Subtitle OCR include top title band")

    if not _use_overlap_reader():
        logger.info("Subtitle OCR overlap disabled (VIDEOSEEK_DISABLE_SUBTITLE_OCR_OVERLAP)")
        for index, (time_sec, frame) in enumerate(iter_frames_at_times(video_path, ordered)):
            if _stopped():
                raise InterruptedError("stopped")
            _note_frame(index)
            bands = crop_subtitle_rois(frame, include_top=include_top_band)
            if not bands:
                stats["blank_skips"] += 1
                continue
            for band, roi in bands:
                if roi_likely_blank(roi):
                    stats["blank_skips"] += 1
                    continue
                _consider_roi(time_sec, np.ascontiguousarray(roi), str(band))
        _flush_pending()
        logger.info(
            "Subtitle OCR probe stats: probed=%d ocr_calls=%d blank_skips=%d unchanged_skips=%d",
            stats["probed"],
            stats["ocr_calls"],
            stats["blank_skips"],
            stats["unchanged_skips"],
        )
        if stats_out is not None:
            stats_out.update(stats)
        return observations

    # Dual-band may enqueue 2 items/frame; keep a bit more headroom.
    band_factor = 2 if include_top_band else 1
    effective_queue = max(
        4,
        int(queue_size) * band_factor,
        batch_n * 3 * band_factor if use_batch else int(queue_size) * band_factor,
    )
    frame_queue: queue.Queue = queue.Queue(maxsize=effective_queue)
    stop_event = threading.Event()
    reader_error: list[BaseException] = []
    reader = threading.Thread(
        target=_reader_loop,
        args=(video_path, ordered, frame_queue, stop_event, reader_error, include_top_band),
        name="VSSubtitleOcrReader",
        daemon=True,
    )
    reader.start()
    try:
        while True:
            if _stopped():
                stop_event.set()
                raise InterruptedError("stopped")
            try:
                item = frame_queue.get(timeout=0.5)
            except queue.Empty:
                if not reader.is_alive() and frame_queue.empty():
                    break
                continue
            if item is None:
                break
            kind = item[0]
            index = int(item[1])
            time_sec = float(item[2])
            band = str(item[3] if len(item) > 3 else "bottom")
            _note_frame(index)
            if kind == "skip":
                stats["blank_skips"] += 1
                continue
            roi = item[4]
            _consider_roi(time_sec, roi, band)
        _flush_pending()
        if reader_error:
            raise reader_error[0]
    finally:
        stop_event.set()
        _drain_queue(frame_queue)
        reader.join(timeout=120.0)
        if reader.is_alive():
            logger.warning("Subtitle OCR reader thread did not stop within join timeout")

    logger.info(
        "Subtitle OCR probe stats: probed=%d ocr_calls=%d blank_skips=%d unchanged_skips=%d",
        stats["probed"],
        stats["ocr_calls"],
        stats["blank_skips"],
        stats["unchanged_skips"],
    )
    if stats_out is not None:
        stats_out.update(stats)
    return observations
