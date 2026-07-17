"""Producer–consumer OCR pipeline (CLIP-index style overlap).

Reader thread decodes/crops while the main thread runs RapidOCR, via a bounded
``queue.Queue``. Disable with ``VIDEOSEEK_DISABLE_SUBTITLE_OCR_OVERLAP=1``.
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
    crop_subtitle_roi,
    iter_frames_at_times,
    roi_likely_blank,
)

logger = get_logger("subtitle_ocr.pipeline")

StopCallback = Callable[[], bool]
ProgressCallback = Callable[[float, str], None]
OcrFn = Callable[[np.ndarray], str]


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
) -> None:
    """Decode + ROI crop (+ blank skip) while OCR consumes on the other side."""
    try:
        for index, (time_sec, frame) in enumerate(iter_frames_at_times(video_path, times)):
            if stop_event.is_set():
                return
            roi = crop_subtitle_roi(frame)
            if roi_likely_blank(roi):
                item: tuple[Any, ...] = ("skip", index, float(time_sec))
            else:
                # Copy so producer can drop the full frame promptly.
                item = ("frame", index, float(time_sec), np.ascontiguousarray(roi))
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
    duration: float = 0.0,
    asr_source: str = "",
    stop_callback: StopCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_base: float = 0.20,
    progress_span: float = 0.70,
    queue_size: int = 12,
) -> list[dict[str, Any]]:
    """Decode/OCR with optional overlap; return raw observations (pre-merge)."""
    ordered = list(times)
    total = max(1, len(ordered))
    observations: list[dict[str, Any]] = []
    last_text = ""

    def _stopped() -> bool:
        return bool(stop_callback and stop_callback())

    def _emit_progress(done: int) -> None:
        if not progress_callback:
            return
        ratio = min(1.0, max(0.0, float(done) / float(total)))
        progress_callback(progress_base + progress_span * ratio, f"subtitle_ocr|{done}|{total}")

    def _accept_text(time_sec: float, text: str) -> None:
        nonlocal last_text
        text = str(text or "").strip()
        if not text:
            return
        if text == last_text and observations:
            observations[-1]["end"] = min(
                duration if duration > 0 else time_sec + 1.2,
                max(float(observations[-1]["end"]), time_sec + 1.0),
            )
            return
        last_text = text
        observations.append(
            {
                "start": max(0.0, time_sec - 0.3),
                "end": min(duration if duration > 0 else time_sec + 1.2, time_sec + 1.2),
                "text": text,
                "language": "",
                "asr_source": asr_source,
            }
        )

    if progress_callback:
        progress_callback(progress_base, f"subtitle_ocr|0|{total}")

    if not ordered:
        return observations

    if not _use_overlap_reader():
        logger.info("Subtitle OCR overlap disabled (VIDEOSEEK_DISABLE_SUBTITLE_OCR_OVERLAP)")
        for index, (time_sec, frame) in enumerate(iter_frames_at_times(video_path, ordered)):
            if _stopped():
                raise InterruptedError("stopped")
            _emit_progress(index + 1)
            roi = crop_subtitle_roi(frame)
            if roi_likely_blank(roi):
                continue
            _accept_text(time_sec, ocr_fn(roi))
        return observations

    frame_queue: queue.Queue = queue.Queue(maxsize=max(4, int(queue_size)))
    stop_event = threading.Event()
    reader_error: list[BaseException] = []
    reader = threading.Thread(
        target=_reader_loop,
        args=(video_path, ordered, frame_queue, stop_event, reader_error),
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
            _emit_progress(index + 1)
            if kind == "skip":
                continue
            roi = item[3]
            _accept_text(time_sec, ocr_fn(roi))
        if reader_error:
            raise reader_error[0]
    finally:
        stop_event.set()
        _drain_queue(frame_queue)
        reader.join(timeout=120.0)
        if reader.is_alive():
            logger.warning("Subtitle OCR reader thread did not stop within join timeout")

    return observations
