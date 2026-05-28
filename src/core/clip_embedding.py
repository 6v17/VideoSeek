import ctypes
import json
import os
import platform
import queue
import site
import subprocess
import sys
import threading
import time

import cv2
import numpy as np
import onnxruntime as ort

from src.app.config import load_config
from src.app.indexing_progress import IndexingProgressReporter
from src.app.logging_utils import get_logger
from src.core.inference_registry import build_inference_engine, register_inference_engine
from src.core.extract_frames import stream_frames_with_ffmpeg, terminate_ffmpeg_process
from src.core.onnx_session import build_session_options as _build_session_options, resolve_embedding_batch_size as _resolve_embedding_batch_size
from src.core.onnx_vision_engine import (
    INFERENCE_LOCK as _INFERENCE_LOCK,
    OnnxVisionBatchMixin,
    format_exception_detail as _format_exception_detail,
    truncate_log_text as _truncate_log_text,
)
from src.core.faiss_index import create_clip_index
from src.core.semantic_chunking import SemanticChunkStreamBuilder, chunk_config_payload
from src.storage.asset_store import save_vector_payload
from src.storage.config_store import (
    get_active_embedding_spec,
    get_active_model_profile,
    get_active_model_resource_dir,
    get_effective_prefer_gpu,
)
from src.core.tokenizer import tokenize
from src.utils import (
    ensure_folder_exists,
    ensure_model_files,
    free_memory,
    get_video_duration_seconds,
    resolve_sampling_fps,
)

logger = get_logger("clip_embedding")
_GPU_PROBE_CACHE = None
_HARD_GPU_RUNTIME_ISSUES = {"windows", "windows_version", "directml", "directx", "msvc"}


class CLIPOnnxEngine(OnnxVisionBatchMixin):
    def __init__(self):
        runtime_config = load_config()
        config_prefer_gpu = get_effective_prefer_gpu(config=runtime_config)
        runtime_plan = prepare_inference_runtime(prefer_gpu=config_prefer_gpu, provider="clip_onnx")
        prefer_gpu = runtime_plan["effective_prefer_gpu"]
        providers = ["CPUExecutionProvider"]
        if prefer_gpu:
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]

        model_paths = ensure_model_files(["clip_visual.onnx", "clip_text.onnx"])
        self.model_paths = dict(model_paths)
        self.visual_session = ort.InferenceSession(
            model_paths["clip_visual.onnx"],
            sess_options=_build_session_options(prefer_gpu),
            providers=providers,
        )
        self.text_session = ort.InferenceSession(
            model_paths["clip_text.onnx"],
            sess_options=_build_session_options(prefer_gpu),
            providers=providers,
        )
        self.active_providers = {
            "visual": self.visual_session.get_providers(),
            "text": self.text_session.get_providers(),
        }
        self.using_gpu = all(
            "DmlExecutionProvider" in provider_list for provider_list in self.active_providers.values()
        )
        self.prefer_gpu = config_prefer_gpu
        self.provider_id = "clip_onnx"
        self.init_vision_batch_state(
            visual_session=self.visual_session,
            embedding_batch_size=_resolve_embedding_batch_size(runtime_config),
            image_size=224,
            using_gpu=self.using_gpu,
            backend_label="GPU" if self.using_gpu else "CPU",
            active_providers=self.active_providers,
        )
        self.runtime_warning = runtime_plan["warning"]
        self.runtime_issue = runtime_plan["issue"]
        self.runtime_diagnostics = dict(runtime_plan.get("diagnostics") or {})
        if prefer_gpu and not self.using_gpu and not self.runtime_warning:
            self.runtime_diagnostics = _build_gpu_runtime_diagnostics()
            self.runtime_issue = self.runtime_diagnostics.get("issue", "unknown")
            self.runtime_warning = (
                "GPU execution is unavailable. ONNX Runtime fell back to CPU. "
                "Verify that onnxruntime-directml is installed and that DirectML / DirectX 12 is available."
            )
        self.backend_label = "GPU" if self.using_gpu else "CPU"
        logger.info(
            "Initialized inference engine: configured_prefer_gpu=%s effective_prefer_gpu=%s backend=%s visual_providers=%s text_providers=%s issue=%s",
            config_prefer_gpu,
            prefer_gpu,
            self.backend_label,
            self.active_providers["visual"],
            self.active_providers["text"],
            self.runtime_issue or "",
        )
        self.mean = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32).reshape(1, 1, 3)
        self.std = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32).reshape(1, 1, 3)

    def visual_model_path(self):
        return self.model_paths["clip_visual.onnx"]

    def visual_input_name(self):
        return "input"

    def preprocess_into(self, img_bgr, out_chw):
        """Normalize one BGR frame into CHW float32 ``out_chw`` shaped (3, 224, 224).

        Frames from ``stream_frames_with_ffmpeg`` are already 224×224; skip resize there.
        File paths may be arbitrary resolution and still need resize.
        """
        img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w = int(img.shape[0]), int(img.shape[1])
        if h != 224 or w != 224:
            interp = cv2.INTER_AREA if (h > 224 or w > 224) else cv2.INTER_LINEAR
            img = cv2.resize(img, (224, 224), interpolation=interp)
        t = img.astype(np.float32, copy=False)
        t *= 1.0 / 255.0
        t -= self.mean
        t /= self.std
        out_chw[:] = np.transpose(t, (2, 0, 1))

    def _preprocess(self, img_bgr):
        out = np.empty((3, 224, 224), dtype=np.float32)
        self.preprocess_into(img_bgr, out)
        return out.reshape(1, 3, 224, 224)

    def encode_text(self, text):
        # Retained intentionally: this public text-encoding entrypoint is
        # reached via helper wrappers and may be missed by static analysis.
        with _INFERENCE_LOCK:
            tokens = tokenize([text]).astype(np.int32)
            feat = self.text_session.run(None, {"input": tokens})[0].astype(np.float32)
            feat /= (np.linalg.norm(feat, axis=-1, keepdims=True) + 1e-10)
            return feat


engine = None


def get_engine():
    global engine
    with _INFERENCE_LOCK:
        config = load_config()
        profile = get_active_model_profile(config=config)
        provider = str(profile.get("provider", "") or "").strip() or "clip_onnx"
        profile_id = str(profile.get("id", "") or "").strip()
        if engine is not None:
            cached_provider = str(getattr(engine, "provider_id", "") or "").strip()
            cached_profile_id = str(getattr(engine, "model_profile_id", "") or "").strip()
            if cached_provider and cached_provider != provider:
                logger.info(
                    "Active inference provider changed (%s -> %s); rebuilding engine",
                    cached_provider,
                    provider,
                )
                engine = None
            elif profile_id and cached_profile_id and cached_profile_id != profile_id:
                logger.info(
                    "Active model profile changed (%s -> %s); rebuilding engine",
                    cached_profile_id,
                    profile_id,
                )
                engine = None
        if engine is None:
            logger.info("Inference engine is not initialized; creating a new runtime instance")
            engine = build_inference_engine(provider)
            engine.provider_id = provider
            engine.model_profile_id = profile_id
            if getattr(engine, "visual_session", None) is None:
                raise RuntimeError(
                    f"Inference engine '{provider}' initialized without a visual ONNX session."
                )
            logger.info(
                "Inference engine ready: provider=%s profile=%s backend=%s",
                provider,
                profile_id or "-",
                getattr(engine, "backend_label", ""),
            )
        return engine


def get_clip_embeddings_batch(frames):
    return get_engine().encode_images(frames)


def get_text_embedding(text):
    return get_engine().encode_text(text)


def get_engine_runtime_warning():
    warning = get_engine().runtime_warning
    return warning.strip()


def get_engine_runtime_status():
    if engine is None:
        config = load_config()
        prefer_gpu = get_effective_prefer_gpu(config=config)
        provider = str(get_active_model_profile(config=config).get("provider", "") or "").strip()
        if not prefer_gpu:
            return {
                "initialized": True,
                "prefer_gpu": prefer_gpu,
                "backend": "CPU",
                "warning": "",
                "issue": "",
                "diagnostics": {},
            }
        if provider != "clip_onnx":
            return {
                "initialized": False,
                "prefer_gpu": prefer_gpu,
                "backend": "",
                "warning": "",
                "issue": "",
                "diagnostics": {},
            }
        probe = dict(_GPU_PROBE_CACHE) if isinstance(_GPU_PROBE_CACHE, dict) else None
        if prefer_gpu and probe:
            if probe.get("ok") or not _should_disable_gpu_for_probe_issue(probe, config=config):
                return {
                    "initialized": True,
                    "prefer_gpu": prefer_gpu,
                    "backend": "GPU",
                    "warning": "" if probe.get("ok") else _build_gpu_probe_soft_warning(probe.get("detail")),
                    "issue": "" if probe.get("ok") else probe.get("issue", ""),
                    "diagnostics": dict(probe.get("diagnostics") or {}),
                }
            return {
                "initialized": True,
                "prefer_gpu": prefer_gpu,
                "backend": "CPU",
                "warning": _build_gpu_runtime_warning(probe.get("detail")),
                "issue": probe.get("issue", ""),
                "diagnostics": dict(probe.get("diagnostics") or {}),
            }
        return {
            "initialized": False,
            "prefer_gpu": prefer_gpu,
            "backend": "",
            "warning": "",
            "issue": "",
            "diagnostics": {},
        }

    return {
        "initialized": True,
        "prefer_gpu": engine.prefer_gpu,
        "backend": engine.backend_label,
        "warning": engine.runtime_warning.strip(),
        "issue": engine.runtime_issue,
        "diagnostics": dict(getattr(engine, "runtime_diagnostics", {}) or {}),
    }


def reset_engine():
    global engine, _GPU_PROBE_CACHE
    with _INFERENCE_LOCK:
        logger.info("Resetting inference engine and cached GPU probe result")
        engine = None
        _GPU_PROBE_CACHE = None


def prepare_inference_runtime(prefer_gpu=None, provider=None):
    runtime_config = load_config()
    configured_prefer_gpu = get_effective_prefer_gpu(config=runtime_config) if prefer_gpu is None else bool(prefer_gpu)
    resolved_provider = str(provider or "").strip()
    if not resolved_provider:
        try:
            resolved_provider = str(get_active_model_profile(config=runtime_config).get("provider", "") or "").strip()
        except Exception:
            resolved_provider = "clip_onnx"
    logger.info("Preparing inference runtime: configured_prefer_gpu=%s", configured_prefer_gpu)
    if not configured_prefer_gpu:
        logger.info("Inference runtime preparation selected CPU because GPU preference is disabled")
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": False,
            "warning": "",
            "issue": "",
            "diagnostics": {},
        }
    if resolved_provider != "clip_onnx":
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": True,
            "warning": "",
            "issue": "",
            "diagnostics": {},
        }

    if _is_gpu_probe_child():
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": True,
            "warning": "",
            "issue": "",
            "diagnostics": {},
        }

    probe = _run_gpu_runtime_probe_once()
    if probe["ok"]:
        logger.info("GPU runtime probe succeeded; DirectML remains enabled for this run")
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": True,
            "warning": "",
            "issue": "",
            "diagnostics": dict(probe.get("diagnostics") or {}),
        }

    if not _should_disable_gpu_for_probe_issue(probe, config=runtime_config):
        warning = _build_gpu_probe_soft_warning(probe["detail"])
        logger.warning(
            "GPU runtime probe was inconclusive; keeping DirectML enabled for this run. issue=%s detail=%s",
            probe["issue"],
            probe["detail"],
        )
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": True,
            "warning": warning,
            "issue": probe["issue"],
            "diagnostics": dict(probe.get("diagnostics") or {}),
        }

    warning = _build_gpu_runtime_warning(probe["detail"])
    logger.warning(
        "GPU runtime probe failed; falling back to CPU. issue=%s detail=%s",
        probe["issue"],
        probe["detail"],
    )
    return {
        "configured_prefer_gpu": configured_prefer_gpu,
        "effective_prefer_gpu": False,
        "warning": warning,
        "issue": probe["issue"],
        "diagnostics": dict(probe.get("diagnostics") or {}),
    }


def gpu_probe_cli_main():
    payload = _run_isolated_gpu_probe()
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


def _run_gpu_runtime_probe_once():
    global _GPU_PROBE_CACHE
    if _GPU_PROBE_CACHE is None:
        logger.info("GPU runtime probe cache miss; launching isolated probe")
        _GPU_PROBE_CACHE = _probe_gpu_runtime_subprocess()
    else:
        logger.info("GPU runtime probe cache hit: ok=%s issue=%s", _GPU_PROBE_CACHE.get("ok"), _GPU_PROBE_CACHE.get("issue", ""))
    return dict(_GPU_PROBE_CACHE)


def _probe_gpu_runtime_subprocess():
    command = _build_gpu_probe_command()
    if not command:
        return {
            "ok": False,
            "issue": "unknown",
            "detail": "Python executable is unavailable for GPU runtime probing.",
            "diagnostics": {"probe_stage": "bootstrap", "failure_kind": "probe_command_unavailable"},
        }

    env = os.environ.copy()
    env["VIDEOSEEK_GPU_PROBE_CHILD"] = "1"
    windows_no_window_kwargs = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        windows_no_window_kwargs["startupinfo"] = startupinfo
        windows_no_window_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    logger.info("Starting GPU runtime probe subprocess: command=%s", command)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=25,
            env=env,
            **windows_no_window_kwargs,
        )
    except subprocess.TimeoutExpired:
        logger.warning("GPU runtime probe subprocess timed out after 25s")
        return {
            "ok": False,
            "issue": "probe_timeout",
            "detail": "GPU runtime probe timed out.",
            "diagnostics": {"probe_stage": "subprocess", "failure_kind": "probe_timeout", "timeout_seconds": 25},
        }
    except Exception as exc:
        logger.exception("GPU runtime probe subprocess failed to start")
        return {
            "ok": False,
            "issue": "probe_launch_failed",
            "detail": str(exc),
            "diagnostics": {
                "probe_stage": "subprocess",
                "failure_kind": "probe_launch_failed",
                "probe_exception_type": exc.__class__.__name__,
                "probe_exception_message": str(exc),
            },
        }

    payload = _parse_gpu_probe_payload(result.stdout)
    logger.info(
        "GPU runtime probe subprocess finished: returncode=%s parsed_ok=%s parsed_issue=%s stdout_tail=%s stderr_tail=%s",
        result.returncode,
        payload.get("ok"),
        payload.get("issue", ""),
        _truncate_log_text(result.stdout),
        _truncate_log_text(result.stderr),
    )
    if result.returncode == 0 and payload.get("ok"):
        return {
            "ok": True,
            "issue": "",
            "detail": "",
            "diagnostics": dict(payload.get("diagnostics") or {}),
        }

    issue = payload.get("issue") or "unknown"
    detail = payload.get("detail") or f"GPU runtime probe exited with code {result.returncode}."
    return {
        "ok": False,
        "issue": issue,
        "detail": detail,
        "diagnostics": dict(payload.get("diagnostics") or {}),
    }


def _build_gpu_probe_command():
    executable = _resolve_probe_executable_path()
    if not executable:
        return []

    executable_lower = executable.lower()
    executable_name = os.path.basename(executable_lower)
    is_python_launcher = executable_name.startswith("python")
    if (executable_lower.endswith(".exe") and not is_python_launcher) or getattr(sys, "frozen", False):
        return [executable, "--gpu-probe"]

    main_script = _resolve_main_script_path()
    if not main_script:
        return []
    return [executable, main_script, "--gpu-probe"]


def _resolve_main_script_path():
    candidate = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "main.py"))
    return candidate if os.path.exists(candidate) else ""


def _resolve_probe_executable_path():
    candidates = [
        str(getattr(sys, "executable", "") or "").strip(),
        str((sys.argv or [""])[0] or "").strip(),
        _get_windows_module_filename(),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if os.path.exists(normalized):
            return normalized
    return ""


def _get_windows_module_filename():
    if os.name != "nt":
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetModuleFileNameW(None, buffer, len(buffer))
        if length <= 0:
            return ""
        return buffer.value[:length]
    except Exception:
        return ""


def _parse_gpu_probe_payload(stdout_text):
    text = str(stdout_text or "").strip()
    if not text:
        return {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _run_isolated_gpu_probe():
    try:
        logger.info("GPU probe child starting DirectML validation")
        model_paths = ensure_model_files(["clip_visual.onnx", "clip_text.onnx"])
        providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        visual_session = ort.InferenceSession(
            model_paths["clip_visual.onnx"],
            sess_options=_build_session_options(True),
            providers=providers,
        )
        text_session = ort.InferenceSession(
            model_paths["clip_text.onnx"],
            sess_options=_build_session_options(True),
            providers=providers,
        )
        active_providers = {
            "visual": visual_session.get_providers(),
            "text": text_session.get_providers(),
        }
        diagnostics = _build_gpu_runtime_diagnostics()
        diagnostics["probe_stage"] = "provider_activation"
        diagnostics["active_providers"] = dict(active_providers)
        logger.info("GPU probe child initialized sessions with providers: visual=%s text=%s", active_providers["visual"], active_providers["text"])
        using_gpu = all("DmlExecutionProvider" in provider_list for provider_list in active_providers.values())
        if not using_gpu:
            if "DmlExecutionProvider" not in active_providers["visual"]:
                issue = "visual_provider_not_activated"
            elif "DmlExecutionProvider" not in active_providers["text"]:
                issue = "text_provider_not_activated"
            else:
                issue = diagnostics.get("issue") or "provider_not_activated"
            diagnostics["failure_kind"] = issue
            logger.warning("GPU probe child did not activate DirectML provider: issue=%s", issue or "unknown")
            return {
                "ok": False,
                "issue": issue or "unknown",
                "detail": "DirectML provider was not activated during GPU runtime probe.",
                "diagnostics": diagnostics,
            }

        dummy_image = np.zeros((1, 3, 224, 224), dtype=np.float32)
        try:
            visual_session.run(None, {"input": dummy_image})
        except Exception as exc:
            diagnostics["probe_stage"] = "visual_inference"
            diagnostics["failure_kind"] = "visual_probe_failed"
            diagnostics["probe_exception_type"] = exc.__class__.__name__
            diagnostics["probe_exception_message"] = str(exc)
            logger.exception("GPU probe child failed during visual DirectML validation")
            return {
                "ok": False,
                "issue": "visual_probe_failed",
                "detail": str(exc),
                "diagnostics": diagnostics,
            }
        dummy_tokens = tokenize(["gpu probe"]).astype(np.int32)
        try:
            text_session.run(None, {"input": dummy_tokens})
        except Exception as exc:
            diagnostics["probe_stage"] = "text_inference"
            diagnostics["failure_kind"] = "text_probe_failed"
            diagnostics["probe_exception_type"] = exc.__class__.__name__
            diagnostics["probe_exception_message"] = str(exc)
            logger.exception("GPU probe child failed during text DirectML validation")
            return {
                "ok": False,
                "issue": "text_probe_failed",
                "detail": str(exc),
                "diagnostics": diagnostics,
            }
        logger.info("GPU probe child completed DirectML validation successfully")
        diagnostics.pop("probe_stage", None)
        diagnostics.pop("failure_kind", None)
        diagnostics.pop("probe_exception_type", None)
        diagnostics.pop("probe_exception_message", None)
        return {
            "ok": True,
            "issue": "",
            "detail": "",
            "diagnostics": diagnostics,
        }
    except Exception as exc:
        diagnostics = _build_gpu_runtime_diagnostics()
        diagnostics["probe_stage"] = "session_init"
        diagnostics["failure_kind"] = "session_init_failed"
        diagnostics["probe_exception_type"] = exc.__class__.__name__
        diagnostics["probe_exception_message"] = str(exc)
        issue = diagnostics.get("issue") or "session_init_failed"
        logger.exception("GPU probe child failed during DirectML validation")
        return {
            "ok": False,
            "issue": issue or "unknown",
            "detail": str(exc),
            "diagnostics": diagnostics,
        }


def _build_gpu_runtime_warning(detail):
    base = (
        "GPU execution is unavailable. ONNX Runtime fell back to CPU. "
        "Verify that onnxruntime-directml is installed and that DirectML / DirectX 12 is available."
    )
    detail_text = str(detail or "").strip()
    if not detail_text:
        return base
    return f"{base} Detail: {detail_text}"


def _build_gpu_probe_soft_warning(detail):
    base = (
        "GPU runtime probe was inconclusive. VideoSeek will still try DirectML for this run and fall back to CPU only if actual inference fails."
    )
    detail_text = str(detail or "").strip()
    if not detail_text:
        return base
    return f"{base} Detail: {detail_text}"


def _is_gpu_probe_child():
    return os.environ.get("VIDEOSEEK_GPU_PROBE_CHILD") == "1"


def _should_disable_gpu_for_probe_issue(probe, config=None):
    issue = str((probe or {}).get("issue") or "").strip().lower()
    if issue == "unknown":
        runtime_config = dict(config or load_config())
        return not bool(runtime_config.get("gpu_probe_unknown_keep_gpu", False))
    return issue in _HARD_GPU_RUNTIME_ISSUES


def detect_gpu_runtime_issue():
    return _build_gpu_runtime_diagnostics().get("issue", "unknown")


def _build_gpu_runtime_diagnostics():
    diagnostics = {
        "issue": "unknown",
        "os_name": os.name,
        "platform_release": platform.release(),
        "available_providers": _get_available_provider_names(),
        "missing_dlls": [],
        "loaded_dlls": [],
        "missing_msvc_dlls": [],
        "windows_build": None,
    }
    if not _is_windows():
        diagnostics["issue"] = "windows"
        return diagnostics
    if not _is_windows_10_1903_or_newer():
        diagnostics["issue"] = "windows_version"
        diagnostics["windows_build"] = _get_windows_build_number()
        return diagnostics
    if not _is_directml_provider_available():
        diagnostics["issue"] = "directml"
        return diagnostics
    diagnostics["windows_build"] = _get_windows_build_number()

    required_runtime_dlls = ["DirectML.dll", "d3d12.dll"]
    for dll_name in required_runtime_dlls:
        if _can_load_windows_dll(dll_name):
            diagnostics["loaded_dlls"].append(dll_name)
        else:
            diagnostics["missing_dlls"].append(dll_name)
    if diagnostics["missing_dlls"]:
        diagnostics["issue"] = "directx"
        return diagnostics

    required_msvc_dlls = ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"]
    for dll_name in required_msvc_dlls:
        if _can_load_windows_dll(dll_name):
            diagnostics["loaded_dlls"].append(dll_name)
        else:
            diagnostics["missing_msvc_dlls"].append(dll_name)
    if diagnostics["missing_msvc_dlls"]:
        diagnostics["issue"] = "msvc"
        return diagnostics
    return diagnostics


def _get_available_provider_names():
    try:
        providers = ort.get_available_providers()
    except AttributeError:
        return []
    return [str(provider) for provider in providers]


def _get_windows_build_number():
    if not _is_windows():
        return None
    try:
        return int(sys.getwindowsversion().build)
    except AttributeError:
        return None


def _is_directml_provider_available():
    try:
        return "DmlExecutionProvider" in ort.get_available_providers()
    except AttributeError:
        return False


def _is_windows():
    return os.name == "nt"


def _is_windows_10_1903_or_newer():
    if not _is_windows():
        return False

    try:
        version = sys.getwindowsversion()
        return (version.major, version.build) >= (10, 18362)
    except AttributeError:
        pass

    return platform.release() in {"10", "11"}


def _can_load_windows_dll(name):
    if not _is_windows():
        return False

    try:
        ctypes.WinDLL(name)
        return True
    except (AttributeError, OSError):
        return False


def _has_any_prefix(names, prefixes):
    for name in names:
        for prefix in prefixes:
            if name.startswith(prefix):
                return True
    return False


def _collect_available_dll_names():
    names = set()
    for directory in _candidate_dll_dirs():
        try:
            for entry in os.listdir(directory):
                lower_name = entry.lower()
                if lower_name.endswith(".dll"):
                    names.add(lower_name)
        except OSError:
            continue
    return names


def _candidate_dll_dirs():
    directories = []

    for item in os.environ.get("PATH", "").split(os.pathsep):
        item = item.strip().strip('"')
        if item and os.path.isdir(item):
            directories.append(item)

    for package_dir in site.getsitepackages():
        capi_dir = os.path.join(package_dir, "onnxruntime", "capi")
        if os.path.isdir(capi_dir):
            directories.append(capi_dir)

    try:
        user_site = site.getusersitepackages()
    except AttributeError:
        user_site = ""
    if user_site:
        capi_dir = os.path.join(user_site, "onnxruntime", "capi")
        if os.path.isdir(capi_dir):
            directories.append(capi_dir)

    return list(dict.fromkeys(directories))


def _drain_index_frame_queue(frame_queue):
    """Drop pending frames so a blocked reader thread can finish (error paths)."""
    while True:
        try:
            frame_queue.get_nowait()
        except queue.Empty:
            return


def _indexing_should_stop(should_stop_callback, stop_event):
    if stop_event is not None and stop_event.is_set():
        return True
    return bool(should_stop_callback and should_stop_callback())


def _kill_indexing_ffmpeg(process_holder):
    if not process_holder:
        return
    process = process_holder.get("process")
    if process is not None:
        terminate_ffmpeg_process(process)


def _run_indexing_frame_reader(
    video_path,
    frame_queue,
    stop_event,
    reader_error,
    stream_kwargs,
):
    """Background thread: FFmpeg pipe decode runs here while the main thread runs GPU batches."""
    try:
        for frame, timestamp in stream_frames_with_ffmpeg(video_path, **stream_kwargs):
            if stop_event.is_set():
                return
            while True:
                if stop_event.is_set():
                    return
                try:
                    frame_queue.put((frame, timestamp), timeout=0.25)
                    break
                except queue.Full:
                    continue
    except InterruptedError:
        logger.info("Indexing frame reader stopped for %s", os.path.basename(video_path))
    except Exception as exc:
        logger.exception("Indexing frame reader failed for %s", video_path)
        reader_error.append(exc)
    finally:
        try:
            frame_queue.put(None, timeout=30.0)
        except queue.Full:
            # Consumer must drain; avoid hanging forever on a stuck queue.
            logger.warning("Indexing frame queue still full while sending end sentinel for %s", video_path)


def _indexing_use_overlap_frame_reader():
    """Overlap decode (reader thread) with encode (main thread). Disable via VIDEOSEEK_DISABLE_INDEX_FRAME_OVERLAP=1 for A/B."""
    v = os.environ.get("VIDEOSEEK_DISABLE_INDEX_FRAME_OVERLAP", "").strip().lower()
    return v not in ("1", "true", "yes")


def _accumulate_inference_batch(vector_parts, chunk_builder, batch_vectors, timestamp_batch):
    if batch_vectors is None or len(batch_vectors) == 0:
        return 0
    batch_arr = np.asarray(batch_vectors, dtype=np.float32)
    if batch_arr.ndim == 1:
        batch_arr = batch_arr.reshape(1, -1)
    count = int(batch_arr.shape[0])
    vector_parts.append(batch_arr)
    if chunk_builder is not None:
        chunk_builder.extend(batch_arr, timestamp_batch[:count])
    return count


def _estimate_index_frame_total(video_path, config=None):
    duration = get_video_duration_seconds(video_path)
    if duration is None or float(duration) <= 0:
        return 0
    runtime_config = config or load_config()
    fps = resolve_sampling_fps(float(duration), config=runtime_config)
    return max(1, int(round(float(duration) * float(fps))))


def _encode_batched_from_frame_stream(
    frame_stream,
    engine_instance,
    frame_batch_size,
    *,
    should_stop_callback=None,
    process_holder=None,
    stop_event=None,
    progress_reporter=None,
    estimated_frame_total=0,
    vector_parts=None,
    chunk_builder=None,
):
    """Synchronous: pull from ``frame_stream`` and run ``encode_images`` in batches."""
    frame_batch = []
    timestamp_batch = []
    vector_parts = [] if vector_parts is None else vector_parts
    timestamps = []
    frames_decoded = 0
    frames_encoded = 0
    estimated_total = max(0, int(estimated_frame_total or 0))

    if progress_reporter is not None:
        progress_reporter.emit("decode", 0, estimated_total, force=True)

    for frame, timestamp in frame_stream:
        if _indexing_should_stop(should_stop_callback, stop_event):
            _kill_indexing_ffmpeg(process_holder)
            raise InterruptedError("Index update stopped during frame extraction")
        frames_decoded += 1
        if progress_reporter is not None:
            total = max(estimated_total, frames_decoded)
            progress_reporter.emit("decode", frames_decoded, total)
        frame_batch.append(frame)
        timestamp_batch.append(timestamp)
        if len(frame_batch) < frame_batch_size:
            continue
        batch_vectors = get_engine().encode_images(frame_batch)
        if len(batch_vectors) > 0:
            added = _accumulate_inference_batch(vector_parts, chunk_builder, batch_vectors, timestamp_batch)
            timestamps.extend(timestamp_batch[:added])
            frames_encoded += added
            if progress_reporter is not None:
                total = max(estimated_total, frames_decoded, frames_encoded)
                progress_reporter.emit("encode", frames_encoded, total)
        frame_batch = []
        timestamp_batch = []
    if frame_batch:
        batch_vectors = get_engine().encode_images(frame_batch)
        if len(batch_vectors) > 0:
            added = _accumulate_inference_batch(vector_parts, chunk_builder, batch_vectors, timestamp_batch)
            timestamps.extend(timestamp_batch[:added])
            frames_encoded += added
            if progress_reporter is not None:
                total = max(estimated_total, frames_decoded, frames_encoded)
                progress_reporter.emit("encode", frames_encoded, total, force=True)
    if progress_reporter is not None:
        total = max(estimated_total, frames_decoded, frames_encoded)
        progress_reporter.emit("decode", frames_decoded, total, force=True)
        progress_reporter.emit("encode", frames_encoded, total, force=True)

    return timestamps


def generate_vectors_and_index_for_video(
    video_path,
    video_id,
    index_dir,
    vector_dir,
    should_stop_callback=None,
    progress_callback=None,
    file_index=1,
    file_total=1,
):
    wall_start = time.perf_counter()
    log_tag = f"{video_id} {os.path.basename(video_path)}"
    frame_batch = []
    timestamp_batch = []
    vector_parts = []
    timestamps = []
    engine_instance = get_engine()
    frame_batch_size = engine_instance.embedding_batch_size
    pipe_start = time.perf_counter()
    process_holder = {}
    stop_event = threading.Event()
    runtime_config = load_config()
    estimated_frame_total = _estimate_index_frame_total(video_path, config=runtime_config)
    chunk_config = chunk_config_payload(
        similarity_threshold=runtime_config.get("similarity_threshold", 0.85),
        max_chunk_duration=runtime_config.get("max_chunk_duration", 5.0),
        min_chunk_size=runtime_config.get("min_chunk_size", 2),
        similarity_mode=runtime_config.get("chunk_similarity_mode", "chunk"),
    )
    chunk_builder = SemanticChunkStreamBuilder(**chunk_config)
    progress_reporter = (
        IndexingProgressReporter(
            progress_callback,
            video_name=os.path.basename(video_path),
            file_index=file_index,
            file_total=file_total,
        )
        if progress_callback
        else None
    )
    frames_decoded = 0
    frames_encoded = 0

    def _should_stop():
        return _indexing_should_stop(should_stop_callback, stop_event)

    def _report_decode(force=False):
        if progress_reporter is None:
            return
        total = max(estimated_frame_total, frames_decoded, frames_encoded)
        progress_reporter.emit("decode", frames_decoded, total, force=force)

    def _report_encode(force=False):
        if progress_reporter is None:
            return
        total = max(estimated_frame_total, frames_decoded, frames_encoded)
        progress_reporter.emit("encode", frames_encoded, total, force=force)

    stream_kwargs = {
        "should_stop": _should_stop,
        "process_holder": process_holder,
    }

    if progress_reporter is not None:
        progress_reporter.emit("decode", 0, estimated_frame_total, force=True)

    if _indexing_use_overlap_frame_reader():
        frame_queue = queue.Queue(maxsize=max(32, frame_batch_size * 4))
        reader_error = []
        reader_thread = threading.Thread(
            target=_run_indexing_frame_reader,
            args=(video_path, frame_queue, stop_event, reader_error, stream_kwargs),
            name="VSIndexFrameReader",
            daemon=True,
        )
        reader_thread.start()
        try:
            while True:
                if _should_stop():
                    _kill_indexing_ffmpeg(process_holder)
                    raise InterruptedError("Index update stopped during frame extraction")
                try:
                    item = frame_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if item is None:
                    break
                frame, timestamp = item
                frames_decoded += 1
                _report_decode()
                frame_batch.append(frame)
                timestamp_batch.append(timestamp)
                if len(frame_batch) < frame_batch_size:
                    continue
                batch_vectors = get_engine().encode_images(frame_batch)
                if len(batch_vectors) > 0:
                    added = _accumulate_inference_batch(
                        vector_parts, chunk_builder, batch_vectors, timestamp_batch
                    )
                    timestamps.extend(timestamp_batch[:added])
                    frames_encoded += added
                    _report_encode()
                frame_batch = []
                timestamp_batch = []

            if frame_batch:
                batch_vectors = get_engine().encode_images(frame_batch)
                if len(batch_vectors) > 0:
                    added = _accumulate_inference_batch(
                        vector_parts, chunk_builder, batch_vectors, timestamp_batch
                    )
                    timestamps.extend(timestamp_batch[:added])
                    frames_encoded += added
                    _report_encode(force=True)
            _report_decode(force=True)
            _report_encode(force=True)

            if reader_error:
                raise reader_error[0]
        finally:
            stop_event.set()
            _drain_index_frame_queue(frame_queue)
            reader_thread.join(timeout=600.0)
            if reader_thread.is_alive():
                logger.warning("Indexing frame reader thread did not stop within join timeout for %s", video_path)
    else:
        logger.info(
            "Per-video index %s: overlap reader disabled (VIDEOSEEK_DISABLE_INDEX_FRAME_OVERLAP)",
            log_tag,
        )
        timestamps = _encode_batched_from_frame_stream(
            stream_frames_with_ffmpeg(video_path, **stream_kwargs),
            engine_instance,
            frame_batch_size,
            should_stop_callback=should_stop_callback,
            process_holder=process_holder,
            stop_event=stop_event,
            progress_reporter=progress_reporter,
            estimated_frame_total=estimated_frame_total,
            vector_parts=vector_parts,
            chunk_builder=chunk_builder,
        )

    pipe_s = time.perf_counter() - pipe_start
    logger.info("Per-video index %s: decode_queue+encode_batches %.2fs", log_tag, pipe_s)

    if not vector_parts:
        logger.info("Per-video index %s: total %.2fs (no vectors)", log_tag, time.perf_counter() - wall_start)
        return [], [], None

    if progress_reporter is not None:
        progress_reporter.emit("chunk", force=True)
    t_chunks = time.perf_counter()
    chunks = chunk_builder.finish()
    chunks_s = time.perf_counter() - t_chunks

    t_stack = time.perf_counter()
    vectors = np.vstack(vector_parts).astype(np.float32)
    del vector_parts
    stack_s = time.perf_counter() - t_stack
    free_memory()

    vector_file = os.path.normpath(os.path.join(vector_dir, f"{video_id}_vectors.npy"))
    index_file = os.path.normpath(os.path.join(index_dir, f"{video_id}_index.faiss"))

    ensure_folder_exists(vector_file)
    if progress_reporter is not None:
        progress_reporter.emit("save", force=True)
    t_save = time.perf_counter()
    save_vector_payload(
        vectors,
        timestamps,
        vector_file,
        chunks=chunks,
        chunk_config=chunk_config,
        embedding_spec=get_active_embedding_spec(config=runtime_config),
    )
    save_s = time.perf_counter() - t_save

    ensure_folder_exists(index_file)
    t_faiss = time.perf_counter()
    index = create_clip_index(vectors, index_file)
    faiss_s = time.perf_counter() - t_faiss

    total_s = time.perf_counter() - wall_start
    parts_s = pipe_s + stack_s + chunks_s + save_s + faiss_s
    logger.info(
        "Per-video index %s: stack_vectors %.2fs semantic_chunks %.2fs save_payload %.2fs faiss_index %.2fs "
        "| parts_sum=%.2fs wall_total=%.2fs",
        log_tag,
        stack_s,
        chunks_s,
        save_s,
        faiss_s,
        parts_s,
        total_s,
    )
    return vectors, timestamps, index


def _register_default_inference_engines():
    register_inference_engine("clip_onnx", lambda: CLIPOnnxEngine())

    def _siglip_factory():
        from src.core.siglip_provider_draft import SigLIP2OnnxEngine

        runtime_config = load_config()
        return SigLIP2OnnxEngine(get_active_model_resource_dir(config=runtime_config))

    register_inference_engine("siglip2_onnx", _siglip_factory)

    def _chinese_clip_factory():
        from src.core.chinese_clip_provider import ChineseCLIPOnnxEngine

        runtime_config = load_config()
        return ChineseCLIPOnnxEngine(get_active_model_resource_dir(config=runtime_config))

    register_inference_engine("chinese_clip_onnx", _chinese_clip_factory)


_register_default_inference_engines()
