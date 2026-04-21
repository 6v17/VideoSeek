import ctypes
import json
import os
import platform
import site
import subprocess
import sys

import cv2
import numpy as np
import onnxruntime as ort

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.core.extract_frames import extract_frames_with_ffmpeg
from src.core.faiss_index import create_clip_index, save_vectors
from src.core.semantic_chunking import build_semantic_chunks, chunk_config_payload
from src.core.tokenizer import tokenize
from src.utils import ensure_folder_exists, ensure_model_files, free_memory, measure_time

logger = get_logger("clip_embedding")
_GPU_PROBE_CACHE = None


class CLIPOnnxEngine:
    def __init__(self):
        config_prefer_gpu = load_config().get("prefer_gpu", True)
        runtime_plan = prepare_inference_runtime(prefer_gpu=config_prefer_gpu)
        prefer_gpu = runtime_plan["effective_prefer_gpu"]
        providers = ["CPUExecutionProvider"]
        if prefer_gpu:
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]

        model_paths = ensure_model_files(["clip_visual.onnx", "clip_text.onnx"])
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
        self.runtime_warning = runtime_plan["warning"]
        self.runtime_issue = runtime_plan["issue"]
        if prefer_gpu and not self.using_gpu and not self.runtime_warning:
            self.runtime_issue = detect_gpu_runtime_issue()
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
        self._feature_dim = None

    def _preprocess(self, img_bgr):
        img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (224, 224), interpolation=cv2.INTER_CUBIC)
        img = img.astype(np.float32) / 255.0
        img = (img - self.mean) / self.std
        img = img.transpose(2, 0, 1)
        return img[np.newaxis, :].astype(np.float32)

    def imread_chinese(self, path):
        with open(path, "rb") as handle:
            data = handle.read()
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

    def encode_images(self, frames):
        # Retained intentionally: this public image-encoding entrypoint is
        # reached via helper wrappers and may be missed by static analysis.
        if self._feature_dim is None:
            dummy = np.zeros((1, 3, 224, 224), dtype=np.float32)
            dummy_feat = self.visual_session.run(None, {"input": dummy})[0]
            self._feature_dim = dummy_feat.shape[1] if dummy_feat.ndim > 1 else dummy_feat.shape[0]

        embeddings = []
        for frame in frames:
            image = self.imread_chinese(frame) if isinstance(frame, str) else frame
            if image is None:
                continue
            blob = self._preprocess(image)
            feat = self.visual_session.run(None, {"input": blob})[0].astype(np.float32)
            feat /= (np.linalg.norm(feat, axis=-1, keepdims=True) + 1e-10)
            embeddings.append(feat)

        if not embeddings:
            return np.empty((0, self._feature_dim), dtype=np.float32)
        free_memory()
        return np.vstack(embeddings)

    def encode_text(self, text):
        # Retained intentionally: this public text-encoding entrypoint is
        # reached via helper wrappers and may be missed by static analysis.
        tokens = tokenize([text]).astype(np.int32)
        feat = self.text_session.run(None, {"input": tokens})[0].astype(np.float32)
        feat /= (np.linalg.norm(feat, axis=-1, keepdims=True) + 1e-10)
        return feat


engine = None


def get_engine():
    global engine
    if engine is None:
        logger.info("Inference engine is not initialized; creating a new runtime instance")
        engine = CLIPOnnxEngine()
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
        prefer_gpu = load_config().get("prefer_gpu", True)
        if not prefer_gpu:
            return {
                "initialized": True,
                "prefer_gpu": prefer_gpu,
                "backend": "CPU",
                "warning": "",
                "issue": "",
            }
        probe = dict(_GPU_PROBE_CACHE) if isinstance(_GPU_PROBE_CACHE, dict) else None
        if prefer_gpu and probe:
            if probe.get("ok"):
                return {
                    "initialized": True,
                    "prefer_gpu": prefer_gpu,
                    "backend": "GPU",
                    "warning": "",
                    "issue": "",
                }
            return {
                "initialized": True,
                "prefer_gpu": prefer_gpu,
                "backend": "CPU",
                "warning": _build_gpu_runtime_warning(probe.get("detail")),
                "issue": probe.get("issue", ""),
            }
        return {
            "initialized": False,
            "prefer_gpu": prefer_gpu,
            "backend": "",
            "warning": "",
            "issue": "",
        }

    return {
        "initialized": True,
        "prefer_gpu": engine.prefer_gpu,
        "backend": engine.backend_label,
        "warning": engine.runtime_warning.strip(),
        "issue": engine.runtime_issue,
    }


def reset_engine():
    global engine, _GPU_PROBE_CACHE
    logger.info("Resetting inference engine and cached GPU probe result")
    engine = None
    _GPU_PROBE_CACHE = None


def prepare_inference_runtime(prefer_gpu=None):
    configured_prefer_gpu = load_config().get("prefer_gpu", True) if prefer_gpu is None else bool(prefer_gpu)
    logger.info("Preparing inference runtime: configured_prefer_gpu=%s", configured_prefer_gpu)
    if not configured_prefer_gpu:
        logger.info("Inference runtime preparation selected CPU because GPU preference is disabled")
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": False,
            "warning": "",
            "issue": "",
        }

    if _is_gpu_probe_child():
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": True,
            "warning": "",
            "issue": "",
        }

    probe = _run_gpu_runtime_probe_once()
    if probe["ok"]:
        logger.info("GPU runtime probe succeeded; DirectML remains enabled for this run")
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": True,
            "warning": "",
            "issue": "",
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
        }

    env = os.environ.copy()
    env["VIDEOSEEK_GPU_PROBE_CHILD"] = "1"
    logger.info("Starting GPU runtime probe subprocess: command=%s", command)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=25,
            env=env,
        )
    except subprocess.TimeoutExpired:
        logger.warning("GPU runtime probe subprocess timed out after 25s")
        return {
            "ok": False,
            "issue": "unknown",
            "detail": "GPU runtime probe timed out.",
        }
    except Exception as exc:
        logger.exception("GPU runtime probe subprocess failed to start")
        return {
            "ok": False,
            "issue": "unknown",
            "detail": str(exc),
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
        }

    issue = payload.get("issue") or "unknown"
    detail = payload.get("detail") or f"GPU runtime probe exited with code {result.returncode}."
    return {
        "ok": False,
        "issue": issue,
        "detail": detail,
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
        logger.info("GPU probe child initialized sessions with providers: visual=%s text=%s", active_providers["visual"], active_providers["text"])
        using_gpu = all("DmlExecutionProvider" in provider_list for provider_list in active_providers.values())
        if not using_gpu:
            issue = detect_gpu_runtime_issue()
            logger.warning("GPU probe child did not activate DirectML provider: issue=%s", issue or "unknown")
            return {
                "ok": False,
                "issue": issue or "unknown",
                "detail": "DirectML provider was not activated during GPU runtime probe.",
            }

        dummy_image = np.zeros((1, 3, 224, 224), dtype=np.float32)
        visual_session.run(None, {"input": dummy_image})
        dummy_tokens = tokenize(["gpu probe"]).astype(np.int32)
        text_session.run(None, {"input": dummy_tokens})
        logger.info("GPU probe child completed DirectML validation successfully")
        return {
            "ok": True,
            "issue": "",
            "detail": "",
        }
    except Exception as exc:
        issue = detect_gpu_runtime_issue()
        logger.exception("GPU probe child failed during DirectML validation")
        return {
            "ok": False,
            "issue": issue or "unknown",
            "detail": str(exc),
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


def _is_gpu_probe_child():
    return os.environ.get("VIDEOSEEK_GPU_PROBE_CHILD") == "1"


def _truncate_log_text(text, limit=240):
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def detect_gpu_runtime_issue():
    if not _is_windows():
        return "windows"
    if not _is_windows_10_1903_or_newer():
        return "windows_version"
    if not _is_directml_provider_available():
        return "directml"
    if not _can_load_windows_dll("DirectML.dll") or not _can_load_windows_dll("d3d12.dll"):
        return "directx"

    available_names = _collect_available_dll_names()
    if not _has_any_prefix(available_names, ("vcruntime140", "vcruntime140_1", "msvcp140")):
        return "msvc"
    return "unknown"


def _build_session_options(prefer_gpu):
    session_options = ort.SessionOptions()
    if prefer_gpu:
        # DirectML sessions require sequential execution and are more stable with memory pattern disabled.
        session_options.enable_mem_pattern = False
        session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return session_options


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


@measure_time("Video indexing time:")
def generate_vectors_and_index_for_video(video_path, video_id, index_dir, vector_dir):
    frames, timestamps = extract_frames_with_ffmpeg(video_path)
    if not frames:
        raise ValueError(f"No frames extracted from video: {video_path}")

    vectors = get_engine().encode_images(frames)
    if vectors is None or len(vectors) == 0:
        raise ValueError(f"No embeddings generated for video: {video_path}")
    if len(vectors) != len(timestamps):
        raise ValueError(
            f"Embedding count mismatch for video: {video_path} "
            f"(vectors={len(vectors)} timestamps={len(timestamps)})"
        )
    free_memory()
    config = load_config()
    chunk_config = chunk_config_payload(
        similarity_threshold=config.get("similarity_threshold", 0.85),
        max_chunk_duration=config.get("max_chunk_duration", 5.0),
        min_chunk_size=config.get("min_chunk_size", 2),
        similarity_mode=config.get("chunk_similarity_mode", "chunk"),
    )
    chunks = build_semantic_chunks(
        vectors,
        timestamps,
        similarity_threshold=chunk_config["similarity_threshold"],
        max_chunk_duration=chunk_config["max_chunk_duration"],
        min_chunk_size=chunk_config["min_chunk_size"],
        similarity_mode=chunk_config["similarity_mode"],
    )

    vector_file = os.path.normpath(os.path.join(vector_dir, f"{video_id}_vectors.npy"))
    index_file = os.path.normpath(os.path.join(index_dir, f"{video_id}_index.faiss"))

    ensure_folder_exists(vector_file)
    save_vectors(vectors, timestamps, vector_file, chunks=chunks, chunk_config=chunk_config)

    ensure_folder_exists(index_file)
    index = create_clip_index(vectors, index_file)
    return vectors, timestamps, index
