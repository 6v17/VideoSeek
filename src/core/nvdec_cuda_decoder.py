"""PyNvVideoCodec NVDEC decode path — GPU RGB frames for zero-copy indexing."""
from __future__ import annotations

import os
import time
from typing import Any, Iterator

from src.app.logging_utils import get_logger
from src.core.nvdec_dll_bootstrap import ensure_pynvvideocodec_dll_paths
from src.utils import get_video_duration_seconds, get_video_stream_info

logger = get_logger("nvdec_cuda_decoder")

_DECODE_BACKEND_NATIVE = "nvdec_cuda_native"
_DECODE_BACKEND_NATIVE_P010 = "nvdec_cuda_native_p010"
_INDEX_BATCH = 64


def _frame_extraction_error():
    from src.core.extract_frames import FrameExtractionError

    return FrameExtractionError


def _d3d11va_helpers():
    from src.core.extract_frames import _d3d11va_10bit_reason, _d3d11va_hard_skip_reason

    return _d3d11va_hard_skip_reason, _d3d11va_10bit_reason


def _mark_decode_backend(backend: str) -> None:
    from src.core.extract_frames import _set_last_frame_decode_backend

    _set_last_frame_decode_backend(backend)


def is_nvdec_gpu_frame(frame: Any) -> bool:
    if frame is None:
        return False
    if hasattr(frame, "__dlpack__") or hasattr(frame, "__cuda_array_interface__"):
        return True
    mod = type(frame).__module__
    return mod.startswith("PyNvVideoCodec") or "DecodedFrame" in type(frame).__name__


def _record_decode(seconds: float) -> None:
    try:
        from src.core.pipeline_profiler import record_decode

        record_decode(seconds)
    except Exception:
        return


def _resolve_max_dimensions(stream_info: dict) -> tuple[int, int]:
    width = int(stream_info.get("width") or 0)
    height = int(stream_info.get("height") or 0)
    if width <= 0:
        width = 4096
    if height <= 0:
        height = 4096
    return max(width, 64), max(height, 64)


def _import_pynvvideocodec():
    ensure_pynvvideocodec_dll_paths()
    import PyNvVideoCodec as nvc

    return nvc


def _create_decoder(video_path: str, *, ten_bit: bool, gpu_id: int = 0):
    nvc = _import_pynvvideocodec()
    stream_info = get_video_stream_info(video_path)
    max_width, max_height = _resolve_max_dimensions(stream_info)
    return nvc.SimpleDecoder(
        str(video_path),
        gpu_id=int(gpu_id),
        use_device_memory=True,
        max_width=max_width,
        max_height=max_height,
        output_color_type=nvc.OutputColorType.RGB,
    )


def stream_frames_nvdec_cuda(
    video_path: str,
    fps: float,
    *,
    should_stop=None,
    ten_bit: bool = False,
    gpu_id: int = 0,
) -> Iterator[tuple[Any, float]]:
    """Yield ``(gpu_rgb_frame, timestamp_sec)`` sampled at ``fps`` (synthetic timeline)."""
    if fps <= 0:
        raise ValueError("fps must be positive")

    hard_skip_fn, ten_bit_fn = _d3d11va_helpers()
    hard_skip = hard_skip_fn(get_video_stream_info(video_path))
    if hard_skip:
        FrameExtractionError = _frame_extraction_error()
        raise FrameExtractionError(
            f"NVDEC native decode skipped for {video_path}: {hard_skip}",
            video_path=video_path,
        )

    if ten_bit:
        _, ten_bit_fn = _d3d11va_helpers()
        ten_bit_reason = ten_bit_fn(get_video_stream_info(video_path), video_path)
        if not ten_bit_reason:
            ten_bit = False

    backend = _DECODE_BACKEND_NATIVE_P010 if ten_bit else _DECODE_BACKEND_NATIVE
    FrameExtractionError = _frame_extraction_error()
    decoder = None
    count = 0
    try:
        from src.core.gpu_clip_preprocess import _ensure_cupy_cuda_context, retain_nvdec_gpu_frame

        _ensure_cupy_cuda_context(gpu_id)
        decoder = _create_decoder(video_path, ten_bit=ten_bit, gpu_id=gpu_id)
        duration = get_video_duration_seconds(video_path)
        if duration is None or float(duration) <= 0:
            meta = decoder.get_stream_metadata()
            duration = float(getattr(meta, "duration", 0) or 0)
        if duration <= 0:
            raise FrameExtractionError(
                f"Could not determine duration for NVDEC native decode: {video_path}",
                video_path=video_path,
            )

        output_count = max(1, int(round(float(duration) * float(fps))))
        for batch_start in range(0, output_count, _INDEX_BATCH):
            if should_stop and should_stop():
                raise InterruptedError("Frame extraction stopped")

            batch_end = min(output_count, batch_start + _INDEX_BATCH)
            indices = []
            timestamps = []
            for out_idx in range(batch_start, batch_end):
                timestamp = out_idx / float(fps)
                timestamps.append(timestamp)
                indices.append(int(decoder.get_index_from_time_in_seconds(timestamp)))

            decode_t0 = time.perf_counter()
            decoded_frames = decoder.get_batch_frames_by_index(indices)
            _record_decode(time.perf_counter() - decode_t0)

            if len(decoded_frames) != len(timestamps):
                raise FrameExtractionError(
                    f"NVDEC native decode returned {len(decoded_frames)} frames, expected {len(timestamps)}",
                    video_path=video_path,
                    frame_count=count,
                )

            for frame, timestamp in zip(decoded_frames, timestamps):
                if should_stop and should_stop():
                    raise InterruptedError("Frame extraction stopped")
                count += 1
                yield retain_nvdec_gpu_frame(frame), timestamp

        if count == 0:
            raise FrameExtractionError(
                f"NVDEC native decode produced no frames for {video_path} at {float(fps):.3f} FPS",
                video_path=video_path,
                frame_count=0,
            )

        logger.info(
            "NVDEC native frame extraction completed: %s frames for %s at %.3f FPS [%s]",
            count,
            video_path,
            fps,
            backend,
        )
        _mark_decode_backend(backend)
    except (InterruptedError, FrameExtractionError):
        raise
    except Exception as exc:
        logger.error("NVDEC native decode failed for %s: %s", video_path, exc)
        raise FrameExtractionError(
            f"NVDEC native decode failed for {video_path}: {exc}",
            video_path=video_path,
            frame_count=count,
        ) from exc
    finally:
        if decoder is not None:
            try:
                decoder.stop()
            except Exception:
                pass


def stream_frames_nvdec_cuda_with_fallback(
    video_path: str,
    fps: float,
    *,
    should_stop=None,
    gpu_id: int = 0,
) -> Iterator[tuple[Any, float]]:
    """Try 10-bit native path first when the stream looks 10-bit, else 8-bit."""
    stream_info = get_video_stream_info(video_path)
    _, ten_bit_fn = _d3d11va_helpers()
    ten_bit = bool(ten_bit_fn(stream_info, video_path))
    if ten_bit:
        try:
            yield from stream_frames_nvdec_cuda(
                video_path,
                fps,
                should_stop=should_stop,
                ten_bit=True,
                gpu_id=gpu_id,
            )
            return
        except _frame_extraction_error() as exc:
            if exc.frame_count > 0:
                raise
            logger.warning(
                "NVDEC native 10-bit decode failed for %s, retrying 8-bit RGB: %s",
                os.path.basename(video_path),
                exc,
            )
    yield from stream_frames_nvdec_cuda(
        video_path,
        fps,
        should_stop=should_stop,
        ten_bit=False,
        gpu_id=gpu_id,
    )
