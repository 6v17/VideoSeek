import os
import platform
import subprocess
import threading
import time

import numpy as np

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.utils import (
    get_ffmpeg_path,
    get_video_duration_seconds,
    get_video_stream_info,
    resolve_sampling_fps,
)

logger = get_logger("extract_frames")

# Software decode + CPU filters; FFmpeg outputs 224×224 BGR rawvideo on stdout.
_VF_CPU = "fps={fps:.6f},scale=224:224:flags=fast_bilinear"
_VF_HW = "hwdownload,format=nv12," + _VF_CPU
_VF_HW_10BIT = "hwdownload,format=p010le,format=yuv420p," + _VF_CPU
# NVDEC: scale on GPU first, then download small 224×224 frames (CUDA experiment path).
_VF_NVDEC_GPU_SCALE = "scale_cuda=224:224,hwdownload,format=nv12,fps={fps:.6f},format=bgr24"
_VF_NVDEC_GPU_SCALE_10BIT = (
    "scale_cuda=224:224,hwdownload,format=p010le,fps={fps:.6f},format=yuv420p,format=bgr24"
)
_FRAME_SIZE = 224 * 224 * 3
_DEFAULT_READ_TIMEOUT_SEC = 600.0
_DECODE_BACKEND_CPU = "cpu"
_DECODE_BACKEND_D3D11VA = "d3d11va"
_DECODE_BACKEND_D3D11VA_10BIT = "d3d11va_p010"
_DECODE_BACKEND_NVDEC = "nvdec"
_DECODE_BACKEND_NVDEC_10BIT = "nvdec_p010"
_DECODE_BACKEND_NVDEC_CUDA_SCALE = "nvdec_cuda_scale"
_DECODE_BACKEND_NVDEC_CUDA_SCALE_10BIT = "nvdec_cuda_scale_p010"
_DECODE_BACKEND_NVDEC_CUDA_NATIVE = "nvdec_cuda_native"
_DECODE_BACKEND_NVDEC_CUDA_NATIVE_P010 = "nvdec_cuda_native_p010"
_HW_DECODE_BACKENDS = {
    _DECODE_BACKEND_D3D11VA,
    _DECODE_BACKEND_D3D11VA_10BIT,
    _DECODE_BACKEND_NVDEC,
    _DECODE_BACKEND_NVDEC_10BIT,
    _DECODE_BACKEND_NVDEC_CUDA_SCALE,
    _DECODE_BACKEND_NVDEC_CUDA_SCALE_10BIT,
    _DECODE_BACKEND_NVDEC_CUDA_NATIVE,
    _DECODE_BACKEND_NVDEC_CUDA_NATIVE_P010,
}

_D3D11VA_PROBE_CACHE = None
_CUDA_HWACCEL_PROBE_CACHE = None
_SCALE_CUDA_PROBE_CACHE = None
_NVIDIA_GPU_PROBE_CACHE = None
_PYNVVC_PROBE_CACHE = None
_CUPY_PROBE_CACHE = None
_LAST_FRAME_DECODE_BACKEND = _DECODE_BACKEND_CPU


class FrameExtractionError(RuntimeError):
    """FFmpeg frame extraction failed or produced an unusable stream."""

    def __init__(self, message, *, video_path="", exit_code=None, frame_count=0):
        super().__init__(message)
        self.video_path = video_path
        self.exit_code = exit_code
        self.frame_count = int(frame_count or 0)


def get_last_frame_decode_backend():
    """Backend used by the most recent completed frame extraction."""
    return _LAST_FRAME_DECODE_BACKEND


def _is_cuda_inference_mode():
    try:
        from src.core.inference_providers import is_cuda_inference_mode

        return is_cuda_inference_mode()
    except Exception:
        return False


def is_gpu_decode_experiment_active(config=None):
    """True when GPU decode paths may be attempted (CUDA lab mode or settings toggle)."""
    if platform.system().lower() != "windows":
        return False

    force = os.environ.get("VIDEOSEEK_FORCE_HW_DECODE", "").strip().lower()
    if force in {"1", "true", "yes", "on"}:
        return True
    if force in {"0", "false", "no", "off"}:
        return False

    if _is_cuda_inference_mode():
        return True

    runtime_config = config or load_config()
    return bool(runtime_config.get("experimental_hw_decode", False))


def get_frame_decode_status(config=None):
    """Snapshot for settings diagnostics."""
    runtime_config = config or load_config()
    gpu_decode_active = is_gpu_decode_experiment_active(config=runtime_config)
    requested = is_experimental_hw_decode_enabled(config=runtime_config)
    cuda_mode = _is_cuda_inference_mode()
    zero_copy = cuda_zero_copy_indexing_enabled(config=runtime_config) if gpu_decode_active else False
    full_gpu = False
    if zero_copy:
        try:
            from src.core.gpu_vector_ops import full_gpu_indexing_enabled

            full_gpu = full_gpu_indexing_enabled(config=runtime_config)
        except Exception:
            full_gpu = False
    return {
        "requested": requested,
        "cuda_experiment_mode": cuda_mode,
        "gpu_decode_active": gpu_decode_active,
        "cuda_zero_copy_enabled": zero_copy,
        "full_gpu_indexing_enabled": full_gpu,
        "pynvvideocodec_available": pynvvideocodec_available() if gpu_decode_active else False,
        "cupy_available": cupy_available() if gpu_decode_active else False,
        "d3d11va_available": ffmpeg_supports_d3d11va() if gpu_decode_active else False,
        "cuda_hwaccel_available": ffmpeg_supports_cuda_hwaccel() if gpu_decode_active else False,
        "scale_cuda_available": ffmpeg_supports_scale_cuda() if gpu_decode_active else False,
        "gpu_scale_decode_enabled": gpu_scale_decode_enabled() if gpu_decode_active else False,
        "nvidia_gpu_detected": system_has_nvidia_gpu() if gpu_decode_active else False,
        "last_backend": get_last_frame_decode_backend(),
        "platform": platform.system(),
    }


def pynvvideocodec_available(*, force_refresh=False):
    """Return whether PyNvVideoCodec can be imported (CUDA 12 runtime DLLs present)."""
    global _PYNVVC_PROBE_CACHE
    if not force_refresh and _PYNVVC_PROBE_CACHE is not None:
        return _PYNVVC_PROBE_CACHE
    available = False
    try:
        from src.core.nvdec_dll_bootstrap import ensure_pynvvideocodec_dll_paths

        ensure_pynvvideocodec_dll_paths()
        import PyNvVideoCodec  # noqa: F401

        available = True
    except Exception as exc:
        logger.info("PyNvVideoCodec is unavailable: %s", exc)
        available = False
    _PYNVVC_PROBE_CACHE = available
    return available


def cupy_available(*, force_refresh=False):
    """Return whether CuPy is importable."""
    global _CUPY_PROBE_CACHE
    if not force_refresh and _CUPY_PROBE_CACHE is not None:
        return _CUPY_PROBE_CACHE
    try:
        from src.core.gpu_clip_preprocess import cupy_available as _gpu_cupy_available

        available = _gpu_cupy_available(force_refresh=force_refresh)
    except Exception as exc:
        logger.info("CuPy is unavailable: %s", exc)
        available = False
    _CUPY_PROBE_CACHE = available
    return available


def cuda_zero_copy_indexing_enabled(config=None):
    """True when NVDEC native GPU decode + GPU preprocess + ORT CUDA input may be used."""
    force = os.environ.get("VIDEOSEEK_CUDA_ZERO_COPY", "").strip().lower()
    if force in {"0", "false", "no", "off"}:
        return False
    if force in {"1", "true", "yes", "on"}:
        return pynvvideocodec_available() and cupy_available()
    if not _is_cuda_inference_mode():
        return False
    if not is_gpu_decode_experiment_active(config=config):
        return False
    if platform.system().lower() != "windows":
        return False
    return (
        pynvvideocodec_available()
        and cupy_available()
        and system_has_nvidia_gpu()
    )


def _set_last_frame_decode_backend(backend):
    global _LAST_FRAME_DECODE_BACKEND
    normalized = str(backend or "").strip().lower()
    allowed = {_DECODE_BACKEND_CPU, *_HW_DECODE_BACKENDS}
    if normalized not in allowed:
        normalized = _DECODE_BACKEND_CPU
    _LAST_FRAME_DECODE_BACKEND = normalized


def _resolve_read_timeout_sec():
    raw = os.environ.get("VIDEOSEEK_FFMPEG_READ_TIMEOUT_SEC", "").strip()
    if not raw:
        return _DEFAULT_READ_TIMEOUT_SEC
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_READ_TIMEOUT_SEC
    if value <= 0:
        return None
    return value


def _ffmpeg_thread_count_token():
    """Return argv token for ``-threads`` (``0`` = FFmpeg default). Override: ``VIDEOSEEK_FFMPEG_THREADS``."""
    raw = os.environ.get("VIDEOSEEK_FFMPEG_THREADS", "").strip()
    if not raw:
        return "0"
    try:
        n = int(raw)
    except ValueError:
        return "0"
    if n <= 0:
        return "0"
    return str(min(n, 16))


def _build_startupinfo():
    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    return startupinfo


def _build_cpu_extract_command(video_path, fps):
    ffmpeg_bin = get_ffmpeg_path()
    return [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        _ffmpeg_thread_count_token(),
        "-i",
        video_path,
        "-vf",
        _VF_CPU.format(fps=float(fps)),
        "-sn",
        "-f",
        "image2pipe",
        "-pix_fmt",
        "bgr24",
        "-vcodec",
        "rawvideo",
        "-",
    ]


def _build_d3d11va_extract_command(video_path, fps, *, ten_bit=False):
    ffmpeg_bin = get_ffmpeg_path()
    vf_template = _VF_HW_10BIT if ten_bit else _VF_HW
    return [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-hwaccel",
        "d3d11va",
        "-hwaccel_output_format",
        "d3d11",
        "-threads",
        _ffmpeg_thread_count_token(),
        "-i",
        video_path,
        "-vf",
        vf_template.format(fps=float(fps)),
        "-sn",
        "-f",
        "image2pipe",
        "-pix_fmt",
        "bgr24",
        "-vcodec",
        "rawvideo",
        "-",
    ]


def _build_nvdec_extract_command(video_path, fps, *, ten_bit=False, gpu_scale=False):
    ffmpeg_bin = get_ffmpeg_path()
    if gpu_scale and ten_bit:
        vf_template = _VF_NVDEC_GPU_SCALE_10BIT
    elif gpu_scale:
        vf_template = _VF_NVDEC_GPU_SCALE
    elif ten_bit:
        vf_template = _VF_HW_10BIT
    else:
        vf_template = _VF_HW
    return [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-hwaccel",
        "cuda",
        "-hwaccel_output_format",
        "cuda",
        "-threads",
        _ffmpeg_thread_count_token(),
        "-i",
        video_path,
        "-vf",
        vf_template.format(fps=float(fps)),
        "-sn",
        "-f",
        "image2pipe",
        "-pix_fmt",
        "bgr24",
        "-vcodec",
        "rawvideo",
        "-",
    ]


def _build_extract_command(video_path, fps, *, decode_backend=_DECODE_BACKEND_CPU):
    if decode_backend == _DECODE_BACKEND_NVDEC_CUDA_SCALE_10BIT:
        return _build_nvdec_extract_command(video_path, fps, ten_bit=True, gpu_scale=True)
    if decode_backend == _DECODE_BACKEND_NVDEC_CUDA_SCALE:
        return _build_nvdec_extract_command(video_path, fps, ten_bit=False, gpu_scale=True)
    if decode_backend == _DECODE_BACKEND_NVDEC_10BIT:
        return _build_nvdec_extract_command(video_path, fps, ten_bit=True)
    if decode_backend == _DECODE_BACKEND_NVDEC:
        return _build_nvdec_extract_command(video_path, fps, ten_bit=False)
    if decode_backend == _DECODE_BACKEND_D3D11VA_10BIT:
        return _build_d3d11va_extract_command(video_path, fps, ten_bit=True)
    if decode_backend == _DECODE_BACKEND_D3D11VA:
        return _build_d3d11va_extract_command(video_path, fps, ten_bit=False)
    return _build_cpu_extract_command(video_path, fps)


def is_experimental_hw_decode_enabled(config=None):
    """True when the lab D3D11VA decode path should be attempted (Windows only)."""
    if platform.system().lower() != "windows":
        return False

    force = os.environ.get("VIDEOSEEK_FORCE_HW_DECODE", "").strip().lower()
    if force in {"1", "true", "yes", "on"}:
        return True
    if force in {"0", "false", "no", "off"}:
        return False

    runtime_config = config or load_config()
    return bool(runtime_config.get("experimental_hw_decode", False))


def ffmpeg_supports_d3d11va(*, force_refresh=False):
    """Return whether the configured FFmpeg binary advertises ``d3d11va``."""
    global _D3D11VA_PROBE_CACHE
    if platform.system().lower() != "windows":
        return False
    if not force_refresh and _D3D11VA_PROBE_CACHE is not None:
        return _D3D11VA_PROBE_CACHE

    supported = False
    try:
        result = subprocess.run(
            [get_ffmpeg_path(), "-hide_banner", "-hwaccels"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            startupinfo=_build_startupinfo(),
        )
        haystack = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
        supported = result.returncode == 0 and "d3d11va" in haystack
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.warning("Failed to probe FFmpeg hwaccels: %s", exc)
        supported = False

    _D3D11VA_PROBE_CACHE = supported
    if not supported:
        logger.info("FFmpeg d3d11va hwaccel is unavailable; experimental hw decode will use CPU fallback")
    return supported


def ffmpeg_supports_cuda_hwaccel(*, force_refresh=False):
    """Return whether the configured FFmpeg binary advertises ``cuda`` hwaccel."""
    global _CUDA_HWACCEL_PROBE_CACHE
    if platform.system().lower() != "windows":
        return False
    if not force_refresh and _CUDA_HWACCEL_PROBE_CACHE is not None:
        return _CUDA_HWACCEL_PROBE_CACHE

    supported = False
    try:
        result = subprocess.run(
            [get_ffmpeg_path(), "-hide_banner", "-hwaccels"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            startupinfo=_build_startupinfo(),
        )
        haystack = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
        tokens = haystack.replace("\r", "\n").replace(",", " ").split()
        supported = result.returncode == 0 and "cuda" in tokens
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.warning("Failed to probe FFmpeg cuda hwaccel: %s", exc)
        supported = False

    _CUDA_HWACCEL_PROBE_CACHE = supported
    if not supported:
        logger.info("FFmpeg cuda hwaccel is unavailable; NVDEC decode will use fallback backends")
    return supported


def ffmpeg_supports_scale_cuda(*, force_refresh=False):
    """Return whether FFmpeg exposes the ``scale_cuda`` filter."""
    global _SCALE_CUDA_PROBE_CACHE
    if platform.system().lower() != "windows":
        return False
    if not force_refresh and _SCALE_CUDA_PROBE_CACHE is not None:
        return _SCALE_CUDA_PROBE_CACHE

    supported = False
    try:
        result = subprocess.run(
            [get_ffmpeg_path(), "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            startupinfo=_build_startupinfo(),
        )
        haystack = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
        supported = result.returncode == 0 and "scale_cuda" in haystack
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.warning("Failed to probe FFmpeg scale_cuda filter: %s", exc)
        supported = False

    _SCALE_CUDA_PROBE_CACHE = supported
    if not supported:
        logger.info("FFmpeg scale_cuda filter is unavailable; NVDEC will download full frames before CPU scale")
    return supported


def gpu_scale_decode_enabled():
    """True when NVDEC should scale on GPU before hwdownload."""
    force = os.environ.get("VIDEOSEEK_GPU_SCALE", "").strip().lower()
    if force in {"0", "false", "no", "off"}:
        return False
    if force in {"1", "true", "yes", "on"}:
        return ffmpeg_supports_scale_cuda()
    return _is_cuda_inference_mode() and ffmpeg_supports_scale_cuda()


def _should_attempt_hw_decode(config=None):
    if not is_gpu_decode_experiment_active(config=config):
        return False
    return ffmpeg_supports_d3d11va()


def _should_attempt_nvdec(config=None):
    if not is_gpu_decode_experiment_active(config=config):
        return False
    if not _is_cuda_inference_mode():
        return False
    return system_has_nvidia_gpu() and ffmpeg_supports_cuda_hwaccel()


def system_has_nvidia_gpu(*, force_refresh=False):
    """Best-effort NVIDIA dGPU/iGPU detection on Windows (experimental 10-bit hw path)."""
    global _NVIDIA_GPU_PROBE_CACHE
    if platform.system().lower() != "windows":
        return False
    if not force_refresh and _NVIDIA_GPU_PROBE_CACHE is not None:
        return _NVIDIA_GPU_PROBE_CACHE

    force = os.environ.get("VIDEOSEEK_FORCE_NVIDIA_GPU", "").strip().lower()
    if force in {"1", "true", "yes", "on"}:
        _NVIDIA_GPU_PROBE_CACHE = True
        return True
    if force in {"0", "false", "no", "off"}:
        _NVIDIA_GPU_PROBE_CACHE = False
        return False

    detected = False
    try:
        result = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "Name"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            startupinfo=_build_startupinfo(),
        )
        detected = "nvidia" in f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.warning("Failed to probe NVIDIA GPU via WMIC: %s", exc)
        detected = False

    _NVIDIA_GPU_PROBE_CACHE = detected
    return detected


def _d3d11va_hard_skip_reason(stream_info):
    """Always skip experimental hw for these streams (any GPU vendor)."""
    if not isinstance(stream_info, dict):
        return ""

    pix_fmt = str(stream_info.get("pix_fmt") or "").lower()
    if pix_fmt in {"yuv444p", "yuv444p10le", "yuv444p12le", "gbrp", "gbrp10le"}:
        return f"unsupported pixel format ({pix_fmt})"
    return ""


def _d3d11va_10bit_reason(stream_info, video_path=""):
    """Return a reason string when the stream looks 10-bit, else empty."""
    if not isinstance(stream_info, dict):
        stream_info = {}

    pix_fmt = str(stream_info.get("pix_fmt") or "").lower()
    if pix_fmt:
        if "10" in pix_fmt or pix_fmt.startswith("p010") or pix_fmt.startswith("p016"):
            return f"10-bit pixel format ({pix_fmt})"

    bits = stream_info.get("bits_per_raw_sample")
    try:
        if bits is not None and int(bits) > 8:
            return f"{int(bits)}-bit stream"
    except (TypeError, ValueError):
        pass

    profile = str(stream_info.get("profile") or "").lower()
    if profile and ("main 10" in profile or profile.endswith("10")):
        return f"10-bit profile ({profile})"

    basename = os.path.basename(str(video_path or "")).lower()
    for token in ("10bit", "10-bit", "hevc-10", "hi10p", "h265-10", "h.265-10"):
        if token in basename:
            return f"10-bit marker in filename ({token})"

    return ""


def _d3d11va_skip_reason(stream_info, video_path=""):
    """Backward-compatible alias for callers/tests."""
    return _d3d11va_hard_skip_reason(stream_info) or _d3d11va_10bit_reason(stream_info, video_path)


def video_likely_supports_d3d11va_decode(video_path):
    """Best-effort ffprobe check for experimental 8-bit D3D11VA."""
    stream_info = get_video_stream_info(video_path)
    return not _d3d11va_hard_skip_reason(stream_info) and not _d3d11va_10bit_reason(stream_info)


def _append_d3d11va_backends(backends, stream_info, video_path):
    hard_skip = _d3d11va_hard_skip_reason(stream_info)
    if hard_skip:
        logger.info(
            "Skipping experimental D3D11VA for %s (%s)",
            os.path.basename(video_path),
            hard_skip,
        )
        return backends

    has_nvidia = system_has_nvidia_gpu()
    ten_bit_reason = _d3d11va_10bit_reason(stream_info, video_path)
    if ten_bit_reason:
        if not has_nvidia:
            logger.info(
                "Skipping experimental D3D11VA for %s (%s); NVIDIA GPU required for 10-bit hw decode",
                os.path.basename(video_path),
                ten_bit_reason,
            )
            return backends
        backends.append(_DECODE_BACKEND_D3D11VA_10BIT)
        return backends

    backends.append(_DECODE_BACKEND_D3D11VA)
    if has_nvidia:
        backends.append(_DECODE_BACKEND_D3D11VA_10BIT)
    return backends


def _append_nvdec_cuda_native_backends(backends, stream_info, video_path, *, config=None):
    if not cuda_zero_copy_indexing_enabled(config=config):
        return backends

    hard_skip = _d3d11va_hard_skip_reason(stream_info)
    if hard_skip:
        logger.info(
            "Skipping NVDEC native for %s (%s)",
            os.path.basename(video_path),
            hard_skip,
        )
        return backends

    ten_bit_reason = _d3d11va_10bit_reason(stream_info, video_path)
    if ten_bit_reason:
        backends.append(_DECODE_BACKEND_NVDEC_CUDA_NATIVE_P010)
    backends.append(_DECODE_BACKEND_NVDEC_CUDA_NATIVE)
    return backends


def _append_nvdec_backends(backends, stream_info, video_path, *, config=None):
    hard_skip = _d3d11va_hard_skip_reason(stream_info)
    if hard_skip:
        logger.info(
            "Skipping NVDEC for %s (%s)",
            os.path.basename(video_path),
            hard_skip,
        )
        return backends

    ten_bit_reason = _d3d11va_10bit_reason(stream_info, video_path)
    use_gpu_scale = gpu_scale_decode_enabled()
    if ten_bit_reason:
        if use_gpu_scale:
            backends.append(_DECODE_BACKEND_NVDEC_CUDA_SCALE_10BIT)
        backends.append(_DECODE_BACKEND_NVDEC_10BIT)
        return backends

    if use_gpu_scale:
        backends.append(_DECODE_BACKEND_NVDEC_CUDA_SCALE)
    backends.append(_DECODE_BACKEND_NVDEC)
    backends.append(_DECODE_BACKEND_NVDEC_10BIT)
    return backends


def _resolve_decode_backends(video_path, config=None):
    decode_override = os.environ.get("VIDEOSEEK_DECODE_BACKEND", "").strip().lower()
    if decode_override == "cpu":
        return [_DECODE_BACKEND_CPU]
    if decode_override in {
        _DECODE_BACKEND_NVDEC,
        _DECODE_BACKEND_NVDEC_10BIT,
        _DECODE_BACKEND_NVDEC_CUDA_SCALE,
        _DECODE_BACKEND_NVDEC_CUDA_SCALE_10BIT,
        _DECODE_BACKEND_NVDEC_CUDA_NATIVE,
        _DECODE_BACKEND_NVDEC_CUDA_NATIVE_P010,
    }:
        return [decode_override, _DECODE_BACKEND_CPU]
    if decode_override in {_DECODE_BACKEND_D3D11VA, _DECODE_BACKEND_D3D11VA_10BIT}:
        return [decode_override, _DECODE_BACKEND_CPU]

    if not is_gpu_decode_experiment_active(config=config):
        return [_DECODE_BACKEND_CPU]

    stream_info = get_video_stream_info(video_path)
    backends = []

    if _should_attempt_nvdec(config=config):
        _append_nvdec_cuda_native_backends(backends, stream_info, video_path, config=config)
        _append_nvdec_backends(backends, stream_info, video_path, config=config)

    if _should_attempt_hw_decode(config=config):
        _append_d3d11va_backends(backends, stream_info, video_path)

    if not backends:
        return [_DECODE_BACKEND_CPU]

    deduped = []
    seen = set()
    for backend in backends:
        if backend in seen:
            continue
        seen.add(backend)
        deduped.append(backend)
    if _DECODE_BACKEND_CPU not in deduped:
        deduped.append(_DECODE_BACKEND_CPU)
    return deduped


def _signed_subprocess_code(code: int) -> int:
    """Normalize Windows unsigned 32-bit process exit codes to signed."""
    if code is None:
        return 0
    code = int(code)
    if code > 0x7FFFFFFF:
        return code - 0x100000000
    return code


def terminate_ffmpeg_process(process):
    if process is None:
        return
    try:
        if process.stdout:
            process.stdout.close()
    except OSError:
        pass
    try:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    except OSError:
        pass


def _read_pipe_bytes(stream, size, *, timeout_sec, should_stop, process):
    """Read exactly ``size`` bytes from a pipe, honoring stop/timeout by killing FFmpeg."""
    if timeout_sec is None and not should_stop:
        return stream.read(size)

    payload = [b""]
    read_error = [None]

    def _worker():
        try:
            payload[0] = stream.read(size)
        except Exception as exc:
            read_error[0] = exc

    thread = threading.Thread(target=_worker, name="VSFfmpegPipeRead", daemon=True)
    thread.start()
    deadline = None if timeout_sec is None else (time.monotonic() + float(timeout_sec))
    while thread.is_alive():
        if should_stop and should_stop():
            terminate_ffmpeg_process(process)
            raise InterruptedError("Frame extraction stopped")
        if deadline is not None and time.monotonic() >= deadline:
            terminate_ffmpeg_process(process)
            raise FrameExtractionError(
                f"Timed out while reading FFmpeg output after {timeout_sec:.0f}s",
            )
        thread.join(timeout=0.25)

    if read_error[0] is not None:
        raise read_error[0]
    return payload[0]


def _stream_rawvideo_frames(
    video_path,
    fps,
    *,
    should_stop=None,
    process_holder=None,
    read_timeout_sec=None,
    command=None,
    decode_backend=_DECODE_BACKEND_CPU,
):
    """Single FFmpeg rawvideo pipe reader (library indexing + remix).

    stderr is discarded instead of piped: piping stderr without draining can fill the OS
    buffer and block FFmpeg mid-stream (looks like 'stuck extracting forever').

    Raises:
        FrameExtractionError: FFmpeg failed or the stream ended abnormally after frames were emitted.
        InterruptedError: ``should_stop`` requested termination.
    """
    if command is None:
        command = _build_extract_command(video_path, fps, decode_backend=decode_backend)
    count = 0
    startupinfo = _build_startupinfo()
    process = None
    timeout_sec = _resolve_read_timeout_sec() if read_timeout_sec is None else read_timeout_sec
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
        )
        if process_holder is not None:
            process_holder["process"] = process

        while True:
            if should_stop and should_stop():
                terminate_ffmpeg_process(process)
                raise InterruptedError("Frame extraction stopped")

            if not process.stdout:
                break

            decode_t0 = time.perf_counter()
            in_bytes = _read_pipe_bytes(
                process.stdout,
                _FRAME_SIZE,
                timeout_sec=timeout_sec,
                should_stop=should_stop,
                process=process,
            )
            if len(in_bytes) != _FRAME_SIZE:
                break

            frame = np.frombuffer(in_bytes, np.uint8).reshape((224, 224, 3))
            try:
                from src.core.pipeline_profiler import record_decode

                record_decode(time.perf_counter() - decode_t0)
            except Exception:
                pass
            timestamp = count / float(fps)
            count += 1
            yield frame, timestamp

        return_code = process.wait(timeout=20)
        signed_code = _signed_subprocess_code(return_code)
        if return_code != 0:
            message = (
                f"FFmpeg frame extraction failed for {video_path} with exit code {return_code} "
                f"(signed {signed_code}) after {count} frame(s) [{decode_backend}]"
            )
            log_fn = (
                logger.warning
                if decode_backend in _HW_DECODE_BACKENDS and count == 0
                else logger.error
            )
            log_fn(message)
            raise FrameExtractionError(
                message,
                video_path=video_path,
                exit_code=signed_code,
                frame_count=count,
            )
        if count == 0:
            if decode_backend in _HW_DECODE_BACKENDS:
                message = (
                    f"Hardware frame extraction produced no frames for {video_path} at {float(fps):.3f} FPS "
                    f"[{decode_backend}]"
                )
                logger.warning(message)
                raise FrameExtractionError(
                    message,
                    video_path=video_path,
                    frame_count=0,
                )
            logger.warning("FFmpeg produced no frames for %s at %.3f FPS", video_path, fps)
            return
        logger.info(
            "Frame extraction completed: %s frames for %s at %.3f FPS [%s]",
            count,
            video_path,
            fps,
            decode_backend,
        )
        _set_last_frame_decode_backend(decode_backend)
    except (FrameExtractionError, InterruptedError):
        raise
    except Exception as exc:
        logger.error("Frame extraction crashed for %s: %s", video_path, exc)
        raise FrameExtractionError(
            f"Frame extraction crashed for {video_path}: {exc}",
            video_path=video_path,
            frame_count=count,
        ) from exc
    finally:
        if process_holder is not None:
            process_holder.pop("process", None)
        terminate_ffmpeg_process(process)


def _stream_frames_with_decode_fallback(
    video_path,
    fps,
    *,
    config=None,
    should_stop=None,
    process_holder=None,
    read_timeout_sec=None,
):
    backends = _resolve_decode_backends(video_path, config=config)
    last_error = None
    for index, decode_backend in enumerate(backends):
        command = _build_extract_command(video_path, fps, decode_backend=decode_backend)
        try:
            yield from _stream_rawvideo_frames(
                video_path,
                fps,
                should_stop=should_stop,
                process_holder=process_holder,
                read_timeout_sec=read_timeout_sec,
                command=command,
                decode_backend=decode_backend,
            )
            return
        except InterruptedError:
            raise
        except FrameExtractionError as exc:
            last_error = exc
            has_next_backend = index < len(backends) - 1
            if exc.frame_count > 0 or not has_next_backend:
                raise
            logger.warning(
                "Experimental hw decode (%s) failed for %s, trying next backend: %s",
                decode_backend,
                video_path,
                exc,
            )

    if last_error is not None:
        raise last_error


def stream_frames_with_ffmpeg(
    video_path,
    fps_override=None,
    *,
    should_stop=None,
    process_holder=None,
    read_timeout_sec=None,
):
    """Stream 224×224 BGR frames + timestamps from ``video_path``.

    If ``fps_override`` is set (remix / explicit sampling), it is used as the ``fps=`` filter rate.
    Otherwise the active config sampling rules are used (library indexing).

    Default path uses CPU decode. When GPU decode is active (``VIDEOSEEK_INFERENCE_EP=cuda`` or
    ``experimental_hw_decode``) on Windows, FFmpeg tries NVDEC with GPU-side ``scale_cuda`` first,
    then legacy NVDEC (full-frame hwdownload), then D3D11VA, then CPU.

    Optional env:
    - ``VIDEOSEEK_FFMPEG_THREADS``: FFmpeg ``-threads`` (capped at 16)
    - ``VIDEOSEEK_FFMPEG_READ_TIMEOUT_SEC``: per-read stall timeout (default 600; ``0`` disables)
    - ``VIDEOSEEK_FORCE_HW_DECODE``: force-enable (``1``) or force-disable (``0``) GPU decode
    - ``VIDEOSEEK_GPU_SCALE``: ``auto`` (CUDA mode + scale_cuda), ``1`` force on, ``0`` force off
    - ``VIDEOSEEK_DECODE_BACKEND``: ``auto`` (default), ``nvdec_cuda_native``, ``nvdec_cuda_scale``, ``nvdec``, ``d3d11va``, or ``cpu``
    - ``VIDEOSEEK_CUDA_ZERO_COPY``: ``auto`` (CUDA mode on), ``1`` force on, ``0`` force off
    """
    config = load_config()
    if fps_override is not None:
        fps = float(fps_override)
        if fps <= 0:
            raise ValueError("fps_override must be positive")
    else:
        video_duration = get_video_duration_seconds(video_path)
        fps = resolve_sampling_fps(video_duration, config=config)

    yield from _stream_frames_with_decode_fallback(
        video_path,
        fps,
        config=config,
        should_stop=should_stop,
        process_holder=process_holder,
        read_timeout_sec=read_timeout_sec,
    )


def stream_frames_with_ffmpeg_fixed_fps(video_path, fps):
    """Backward-compatible alias: same as ``stream_frames_with_ffmpeg(..., fps_override=fps)``."""
    yield from stream_frames_with_ffmpeg(video_path, fps_override=float(fps))


def extract_frames_with_ffmpeg(video_path, **stream_kwargs):
    frame_pairs = list(stream_frames_with_ffmpeg(video_path, **stream_kwargs))
    if not frame_pairs:
        return [], []
    frames = [item[0] for item in frame_pairs]
    timestamps = [item[1] for item in frame_pairs]
    return frames, timestamps
