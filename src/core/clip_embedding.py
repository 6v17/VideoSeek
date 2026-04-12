import ctypes
import os
import platform
import site
import sys

import cv2
import numpy as np
import onnxruntime as ort

from src.app.config import load_config
from src.core.extract_frames import extract_frames_with_ffmpeg
from src.core.faiss_index import create_clip_index, save_vectors
from src.core.semantic_chunking import build_semantic_chunks, chunk_config_payload
from src.core.tokenizer import tokenize
from src.utils import ensure_folder_exists, ensure_model_files, free_memory, measure_time


class CLIPOnnxEngine:
    def __init__(self):
        prefer_gpu = load_config().get("prefer_gpu", True)
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
        self.prefer_gpu = prefer_gpu
        self.runtime_warning = ""
        self.runtime_issue = ""
        if prefer_gpu and not self.using_gpu:
            self.runtime_issue = detect_gpu_runtime_issue()
            self.runtime_warning = (
                "GPU execution is unavailable. ONNX Runtime fell back to CPU. "
                "Verify that onnxruntime-directml is installed and that DirectML / DirectX 12 is available."
            )
        self.backend_label = "GPU" if self.using_gpu else "CPU"
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
    global engine
    engine = None


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
        return [], [], None

    vectors = get_engine().encode_images(frames)
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
