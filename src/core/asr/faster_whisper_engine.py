"""faster-whisper runtime for dialogue ASR (CUDA or CPU; not DirectML).

Weights are installed like other understanding models via zip import
(``audio/speech_to_text/faster-whisper-medium``). No auto-download.
CUDA uses float16 only when cuBLAS is actually loadable; otherwise CPU int8.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any

from src.app.logging_utils import get_logger

logger = get_logger("faster_whisper")

WHISPER_COMPONENT_ID = "audio/speech_to_text/faster-whisper-medium"
ASR_SOURCE_ID = WHISPER_COMPONENT_ID
DEFAULT_WHISPER_MODEL_SIZE = "medium"

ProgressCallback = Callable[[float, str], None]

_ENGINE_LOCK = threading.RLock()
_MODEL_CACHE: dict[str, Any] = {}
_CUDA_UNUSABLE_REASON = ""


def is_faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def resolve_installed_whisper_model_dir(*, config=None) -> str | None:
    """Return imported component dir if present and usable."""
    from src.storage.config_store import get_effective_model_dir
    from src.services.understanding_paths import get_component_dir
    from src.services.understanding_resource_service import is_component_installed

    model_root = get_effective_model_dir(config)
    if not is_component_installed(WHISPER_COMPONENT_ID, model_dir=model_root):
        return None
    component_dir = get_component_dir(WHISPER_COMPONENT_ID, model_dir=model_root)
    model_bin = os.path.join(component_dir, "model.bin")
    if not os.path.isfile(model_bin) or os.path.getsize(model_bin) <= 0:
        return None
    return os.path.normpath(os.path.abspath(component_dir))


def resolve_whisper_device() -> tuple[str, str]:
    """Return ``(device, compute_type)``. Prefers CUDA only when cuBLAS is present."""
    global _CUDA_UNUSABLE_REASON
    if _CUDA_UNUSABLE_REASON:
        return "cpu", "int8"
    if _cuda_device_count() <= 0:
        return "cpu", "int8"
    ok, reason = _cuda_runtime_usable()
    if not ok:
        _CUDA_UNUSABLE_REASON = reason or "cuda runtime unusable"
        logger.warning("Faster-Whisper CUDA unavailable (%s); using CPU int8", _CUDA_UNUSABLE_REASON)
        return "cpu", "int8"
    return "cuda", "float16"


def _cuda_device_count() -> int:
    try:
        import ctranslate2

        getter = getattr(ctranslate2, "get_cuda_device_count", None)
        if callable(getter):
            return max(0, int(getter()))
    except Exception:
        pass
    return 0


def _cuda_runtime_usable() -> tuple[bool, str]:
    """Detect common missing CUDA toolkit DLLs (e.g. cublas64_12.dll)."""
    if os.name == "nt":
        missing = _missing_windows_cuda_dlls()
        if missing:
            return False, f"missing {', '.join(missing)}"
    return True, ""


def _missing_windows_cuda_dlls() -> list[str]:
    # CTranslate2 CUDA 12 builds need these; presence of a GPU alone is not enough.
    candidates = ("cublas64_12.dll", "cublasLt64_12.dll")
    missing: list[str] = []
    for name in candidates:
        if _find_dll(name) is None:
            missing.append(name)
    # Only require the primary cublas DLL; Lt is often loaded via the same toolkit.
    if "cublas64_12.dll" in missing:
        return ["cublas64_12.dll"]
    return []


def _find_dll(name: str) -> str | None:
    try:
        import ctypes

        ctypes.WinDLL(name)
        return name
    except Exception:
        pass
    search_dirs: list[str] = []
    cuda_path = str(os.environ.get("CUDA_PATH", "") or "").strip()
    if cuda_path:
        search_dirs.append(os.path.join(cuda_path, "bin"))
    path_env = str(os.environ.get("PATH", "") or "")
    search_dirs.extend([part for part in path_env.split(os.pathsep) if part.strip()])
    for directory in search_dirs:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _is_cuda_runtime_error(exc: BaseException) -> bool:
    text = str(exc or "").lower()
    needles = (
        "cublas",
        "cudnn",
        "cuda",
        "nvrtc",
        "library",
        "cannot be loaded",
        "not found",
    )
    return any(item in text for item in needles)


def get_whisper_model(
    *,
    config=None,
    model_dir: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
):
    if not is_faster_whisper_available():
        raise RuntimeError(
            "faster-whisper is not installed. Install dependencies with: pip install faster-whisper"
        )

    from faster_whisper import WhisperModel

    local_dir = str(model_dir or "").strip() or resolve_installed_whisper_model_dir(config=config)
    if not local_dir or not os.path.isdir(local_dir):
        raise RuntimeError(
            f"Faster-Whisper model not imported. Import understanding zip for {WHISPER_COMPONENT_ID} "
            "(Understanding / Settings → Import Model)."
        )
    model_bin = os.path.join(local_dir, "model.bin")
    if not os.path.isfile(model_bin):
        raise RuntimeError(f"model.bin missing under imported Whisper dir: {local_dir}")

    resolved_device, resolved_compute = resolve_whisper_device()
    device = str(device or resolved_device).strip().lower() or resolved_device
    compute_type = str(compute_type or resolved_compute).strip() or resolved_compute
    cache_key = f"{os.path.normpath(local_dir)}|{device}|{compute_type}"

    with _ENGINE_LOCK:
        cached = _MODEL_CACHE.get(cache_key)
        if cached is not None:
            return cached
        logger.info(
            "Loading imported faster-whisper model_dir=%s device=%s compute_type=%s",
            local_dir,
            device,
            compute_type,
        )
        try:
            model = WhisperModel(
                local_dir,
                device=device,
                compute_type=compute_type,
            )
        except Exception as exc:
            if device != "cpu" and _is_cuda_runtime_error(exc):
                logger.warning("Faster-Whisper CUDA load failed (%s); falling back to CPU", exc)
                return _load_cpu_model_locked(local_dir)
            raise
        _MODEL_CACHE[cache_key] = model
        return model


def _load_cpu_model_locked(local_dir: str):
    global _CUDA_UNUSABLE_REASON
    from faster_whisper import WhisperModel

    _CUDA_UNUSABLE_REASON = _CUDA_UNUSABLE_REASON or "cuda load failed"
    cache_key = f"{os.path.normpath(local_dir)}|cpu|int8"
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached
    model = WhisperModel(local_dir, device="cpu", compute_type="int8")
    _MODEL_CACHE[cache_key] = model
    return model


def clear_whisper_model_cache() -> None:
    with _ENGINE_LOCK:
        _MODEL_CACHE.clear()


def transcribe_wav(
    wav_path: str,
    *,
    config=None,
    language: str = "auto",
    model_dir: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    """Transcribe a 16 kHz mono WAV into dialogue-row dicts (start/end/text/...)."""
    path = os.path.normpath(os.path.abspath(str(wav_path or "").strip()))
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"WAV not found: {wav_path!r}")

    if progress_callback:
        progress_callback(0.0, "whisper_load")
    model = get_whisper_model(config=config, model_dir=model_dir)

    lang = str(language or "auto").strip().lower()
    whisper_language = None if lang in {"", "auto"} else lang

    if progress_callback:
        progress_callback(0.15, "whisper_transcribe")

    try:
        segments, info = model.transcribe(
            path,
            language=whisper_language,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 450},
        )
    except Exception as exc:
        if not _is_cuda_runtime_error(exc):
            raise
        local_dir = str(model_dir or "").strip() or resolve_installed_whisper_model_dir(config=config) or ""
        logger.warning(
            "Faster-Whisper CUDA runtime failed during transcribe (%s); retrying on CPU",
            exc,
        )
        with _ENGINE_LOCK:
            _MODEL_CACHE.clear()
            model = _load_cpu_model_locked(local_dir)
        segments, info = model.transcribe(
            path,
            language=whisper_language,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 450},
        )

    detected = str(getattr(info, "language", "") or "").strip()

    rows: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        text = str(getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        start = float(getattr(segment, "start", 0.0) or 0.0)
        end = float(getattr(segment, "end", start) or start)
        if end < start:
            end = start
        rows.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "language": detected,
                "asr_source": ASR_SOURCE_ID,
            }
        )
        if progress_callback and index % 8 == 0:
            progress_callback(min(0.95, 0.2 + 0.7 * (index + 1) / max(index + 2, 8)), "whisper_segments")

    if progress_callback:
        progress_callback(1.0, "whisper_done")
    return rows
