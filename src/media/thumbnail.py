"""Single-frame thumbnail capture (OpenCV + ffmpeg fallback)."""

from __future__ import annotations

import os
import subprocess
import sys

import numpy as np

from src.app.logging_utils import get_logger
from src.infra.ffmpeg_paths import get_ffmpeg_path

logger = get_logger("thumbnail")


def _cv2():
    import cv2
    from src.app.logging_utils import apply_opencv_log_level

    apply_opencv_log_level()
    return cv2


load_cv2 = _cv2


def _is_http_media_url(path: str) -> bool:
    text = str(path or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _ffmpeg_capture_frame(video_path: str, time_sec: float, *, timeout_sec: float = 3.0):
    ffmpeg_bin = get_ffmpeg_path()
    safe_time = max(0.0, float(time_sec))
    preroll_sec = 0.35
    coarse_seek = max(0.0, safe_time - preroll_sec)
    fine_seek = safe_time - coarse_seek
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{coarse_seek:.3f}",
        "-i",
        video_path,
        "-ss",
        f"{fine_seek:.3f}",
        "-frames:v",
        "1",
        "-f",
        "image2",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    try:
        process = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            timeout=max(1.0, float(timeout_sec)),
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        buffer = np.frombuffer(process.stdout, np.uint8)
        if len(buffer) > 0:
            cv2 = _cv2()
            return cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.warning("Thumbnail capture failed: %s", exc)
    return None


ffmpeg_capture_frame = _ffmpeg_capture_frame


def preview_sample_time(start_sec: float, end_sec: float) -> float:
    """Point hits stay on their timestamp. A real span uses the middle of the clip."""
    start = max(0.0, float(start_sec))
    end = float(end_sec)
    if end > start:
        return (start + end) / 2.0
    return start


def preview_max_drift_sec(start_sec: float, end_sec: float) -> float | None:
    """How far a fast keyframe may sit from the clip middle before ffmpeg is worth it.

    A keyframe near the middle is good enough for a thumbnail. FFmpeg only runs
    when the fast seek lands far away, usually on the opening frame of the clip.
    """
    start = float(start_sec)
    end = float(end_sec)
    if end <= start:
        return None
    return max(1.5, (end - start) * 0.35)


def read_captured_frame(capture, cv2, time_sec: float):
    """Seek with an already-open capture. Returns ``(frame, landed_sec)``."""
    target = max(0.0, float(time_sec))
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, target * 1000.0)
        ok, frame = capture.read()
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "src/media/thumbnail.py:read_captured_frame")
        return None, None
    landed = None
    try:
        pos_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC))
        if pos_ms >= 0:
            landed = pos_ms / 1000.0
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "src/media/thumbnail.py:read_captured_pos")
        landed = None
    if not ok or frame is None or getattr(frame, "size", 0) <= 0:
        return None, landed
    return frame, landed


def _frame_close_enough(landed_sec, target_sec: float, max_drift_sec: float | None) -> bool:
    if max_drift_sec is None or landed_sec is None:
        return True
    return abs(float(landed_sec) - float(target_sec)) <= float(max_drift_sec)


def is_blank_preview_frame(frame) -> bool:
    """True when the frame is a near-uniform black or white flash.

    Samples pixels already in memory. No extra decode.
    """
    if frame is None or getattr(frame, "size", 0) < 16 or getattr(frame, "ndim", 0) < 2:
        return False
    height, width = int(frame.shape[0]), int(frame.shape[1])
    sample = frame[:: max(1, height // 16), :: max(1, width // 16)]
    pixels = np.asarray(sample, dtype=np.float32)
    if pixels.size == 0:
        return False
    mean = float(pixels.mean())
    spread = float(pixels.std())
    if spread > 10.0:
        return False
    return mean < 16.0 or mean > 242.0


def segment_blank_offsets(start_sec: float, end_sec: float) -> tuple[float, float] | None:
    """In-segment times to try after a blank middle: mid + span/4, then mid - span/4."""
    start = float(start_sec)
    end = float(end_sec)
    if end <= start:
        return None
    span = end - start
    mid = (start + end) / 2.0
    return (mid + span / 4.0, mid - span / 4.0)


def nudge_off_blank_frame(
    capture,
    cv2,
    frame,
    _time_sec: float,
    *,
    start_sec: float,
    end_sec: float,
):
    """If the segment middle is a black/white flash, try two other in-segment times.

    Order is the middle (already in ``frame``), then middle + span/4, then
    middle - span/4. Both offsets stay inside the segment. A decoder keyframe
    that lands outside the segment is skipped. If neither offset has content,
    the middle frame is kept. Point hits are not adjusted.
    """
    start = float(start_sec)
    end = float(end_sec)
    if end <= start or not is_blank_preview_frame(frame):
        return frame
    offsets = segment_blank_offsets(start, end)
    if offsets is None:
        return frame
    for candidate in offsets:
        alt, landed = read_captured_frame(capture, cv2, candidate)
        if alt is None or is_blank_preview_frame(alt):
            continue
        if landed is not None and not (start - 0.02 <= float(landed) <= end + 0.02):
            continue
        return alt
    return frame


def get_single_thumbnail(
    video_path,
    time_sec,
    *,
    max_drift_sec: float | None = None,
    segment_start: float | None = None,
    segment_end: float | None = None,
):
    # Retained intentionally: imported dynamically inside ThumbLoader.run().
    path = str(video_path or "").strip()
    if not path:
        return None
    http = _is_http_media_url(path)
    if not http and not os.path.isfile(path):
        return None
    safe_time = max(0.0, float(time_sec))

    # Remote team play URLs: ffmpeg handles HTTP range seeks more reliably than OpenCV.
    # Segment blank retries use the same mid ± span/4 offsets as a local file.
    if http:
        frame = _ffmpeg_capture_frame(path, safe_time, timeout_sec=8.0)
        offsets = None
        if (
            frame is not None
            and segment_start is not None
            and segment_end is not None
        ):
            offsets = segment_blank_offsets(float(segment_start), float(segment_end))
        if frame is not None and offsets is not None and is_blank_preview_frame(frame):
            for candidate in offsets:
                alt = _ffmpeg_capture_frame(path, candidate, timeout_sec=8.0)
                if alt is not None and not is_blank_preview_frame(alt):
                    return alt
        return frame

    # Fast path: one lightweight seek. OpenCV stops on the previous keyframe, which
    # is usually still near the middle of a clip. FFmpeg only if that frame is far off.
    cv2 = _cv2()
    capture = cv2.VideoCapture(path)
    try:
        if capture.isOpened():
            frame, landed = read_captured_frame(capture, cv2, safe_time)
            if frame is not None and _frame_close_enough(landed, safe_time, max_drift_sec):
                if (
                    segment_start is not None
                    and segment_end is not None
                    and float(segment_end) > float(segment_start)
                ):
                    return nudge_off_blank_frame(
                        capture,
                        cv2,
                        frame,
                        safe_time,
                        start_sec=float(segment_start),
                        end_sec=float(segment_end),
                    )
                # Frame hits stay on their timestamp. A blank keyframe is rare, so
                # one accurate seek is cheap and usually lands on the real picture.
                if is_blank_preview_frame(frame):
                    accurate = _ffmpeg_capture_frame(path, safe_time, timeout_sec=3.0)
                    if accurate is not None:
                        return accurate
                return frame
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "src/media/thumbnail.py:capture_read")
    finally:
        capture.release()

    return _ffmpeg_capture_frame(path, safe_time, timeout_sec=3.0)


def draw_top_caption_bar(frame_bgr, text: str, *, bar_height: int = 28):
    """Dark bar + ASCII caption. OpenCV Hershey cannot render CJK reliably."""
    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return frame_bgr
    label = str(text or "").strip()
    if not label:
        return frame_bgr
    cv2 = _cv2()
    height, width = int(frame_bgr.shape[0]), int(frame_bgr.shape[1])
    bar_h = max(18, min(int(bar_height), max(18, height // 5)))
    canvas = np.zeros((height + bar_h, width, 3), dtype=frame_bgr.dtype)
    canvas[bar_h:, :, :] = frame_bgr
    canvas[:bar_h, :, :] = (32, 32, 32)
    scale = 0.42 if width >= 160 else 0.36
    cv2.putText(
        canvas,
        label[:48],
        (6, bar_h - 8),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (240, 240, 240),
        1,
        cv2.LINE_AA,
    )
    return canvas


def compose_side_by_side_bgr(left_bgr, right_bgr, *, left_caption: str = "", right_caption: str = ""):
    """Resize to a shared height and concatenate left|right. Missing side is skipped."""
    frames = [frame for frame in (left_bgr, right_bgr) if frame is not None and getattr(frame, "size", 0)]
    captions = []
    if left_bgr is not None and getattr(left_bgr, "size", 0):
        captions.append(str(left_caption or ""))
    if right_bgr is not None and getattr(right_bgr, "size", 0) and len(frames) > 1:
        captions.append(str(right_caption or ""))
    if not frames:
        return None
    if len(frames) == 1:
        caption = captions[0] if captions else str(left_caption or right_caption or "")
        return draw_top_caption_bar(frames[0], caption) if caption else frames[0]
    cv2 = _cv2()
    left, right = frames[0], frames[1]
    height = min(int(left.shape[0]), int(right.shape[0]))
    if height <= 0:
        return left

    def _resize(frame):
        if int(frame.shape[0]) == height:
            return frame
        width = max(1, int(round(frame.shape[1] * (height / float(frame.shape[0])))))
        return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)

    left_r = _resize(left)
    right_r = _resize(right)
    if captions:
        left_r = draw_top_caption_bar(left_r, captions[0] if len(captions) > 0 else "")
        right_r = draw_top_caption_bar(right_r, captions[1] if len(captions) > 1 else "")
    return cv2.hconcat([left_r, right_r])


def compose_quad_bgr(frames, *, captions: list[str] | None = None):
    """2x2 grid in input order: top-left, top-right, bottom-left, bottom-right."""
    usable = [frame for frame in list(frames or []) if frame is not None and getattr(frame, "size", 0)]
    if len(usable) < 4:
        if len(usable) >= 2:
            return compose_side_by_side_bgr(usable[0], usable[1])
        return usable[0] if usable else None
    cv2 = _cv2()
    height = min(int(frame.shape[0]) for frame in usable[:4])
    if height <= 0:
        return usable[0]

    def _resize(frame):
        if int(frame.shape[0]) == height:
            return frame
        width = max(1, int(round(frame.shape[1] * (height / float(frame.shape[0])))))
        return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)

    cells = [_resize(frame) for frame in usable[:4]]
    labels = list(captions or [])
    if any(str(label or "").strip() for label in labels[:4]):
        cells = [
            draw_top_caption_bar(cell, str(labels[index] if index < len(labels) else ""))
            for index, cell in enumerate(cells)
        ]
    top = cv2.hconcat(cells[:2])
    bottom = cv2.hconcat(cells[2:4])
    width = min(int(top.shape[1]), int(bottom.shape[1]))
    if int(top.shape[1]) != width:
        top = cv2.resize(top, (width, int(top.shape[0])), interpolation=cv2.INTER_AREA)
    if int(bottom.shape[1]) != width:
        bottom = cv2.resize(bottom, (width, int(bottom.shape[0])), interpolation=cv2.INTER_AREA)
    return cv2.vconcat([top, bottom])
