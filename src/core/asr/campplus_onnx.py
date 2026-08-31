"""CAM++ speaker embedding via ONNX Runtime (no FunASR / PyTorch).

Expected graph (3D-Speaker / FunASR export):
  input  ``feature``   [batch, frames, 80] float32
  output ``embedding`` [batch, 192] float32
External data file ``campplus.onnx.data`` must sit next to the graph.
"""

from __future__ import annotations

import os
import shutil
import threading
import zipfile

import numpy as np
import onnxruntime as ort

from src.core.asr.fbank_kaldi import compute_fbank
from src.core.onnx_session import build_session_options, resolve_onnx_providers

DEFAULT_SAMPLE_RATE = 16000
EMBEDDING_DIM = 192
BUNDLED_CAMPPLUS_RELPATH = os.path.join("resources", "asr", "campplus.onnx")
_ENGINE_LOCK = threading.RLock()
_ENGINE_CACHE: dict[str, "CampplusOnnxEngine"] = {}


def _is_ready_onnx(path: str) -> bool:
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        return False
    sibling = path + ".data"
    if os.path.isfile(sibling):
        return os.path.getsize(sibling) > 0
    return os.path.getsize(path) > 5 * 1024 * 1024


def campplus_install_dir(*, model_dir: str | None = None) -> str:
    root = str(model_dir or "").strip()
    if not root:
        try:
            from src.infra.model_paths import get_configured_model_dir

            root = str(get_configured_model_dir() or "").strip()
        except Exception:
            root = ""
    if not root:
        from src.infra.paths import get_default_model_dir

        root = get_default_model_dir()
    return os.path.normpath(os.path.join(root, "campplus"))


def resolve_campplus_model_path(
    *,
    explicit_path: str | None = None,
    model_dir: str | None = None,
) -> str | None:
    candidates: list[str] = []
    explicit = str(explicit_path or os.environ.get("VIDEOSEEK_CAMPPLUS_PATH", "") or "").strip()
    if explicit:
        candidates.append(explicit)

    try:
        from src.infra.paths import get_resource_path

        candidates.append(get_resource_path(BUNDLED_CAMPPLUS_RELPATH))
    except Exception:
        pass

    install_dir = campplus_install_dir(model_dir=model_dir)
    candidates.append(os.path.join(install_dir, "campplus.onnx"))
    if model_dir:
        candidates.append(os.path.join(str(model_dir), "campplus.onnx"))
        candidates.append(os.path.join(str(model_dir), "campplus", "campplus.onnx"))

    seen: set[str] = set()
    for path in candidates:
        normalized = os.path.normpath(os.path.abspath(str(path)))
        if normalized in seen:
            continue
        seen.add(normalized)
        if _is_ready_onnx(normalized):
            return normalized
    return None


def install_campplus_from_zip(zip_path: str, *, dest_dir: str | None = None) -> str:
    """Extract ``campplus.onnx`` + ``campplus.onnx.data`` from an export zip."""
    source = os.path.normpath(os.path.abspath(str(zip_path or "").strip()))
    if not source or not os.path.isfile(source):
        raise FileNotFoundError(f"CAM++ zip not found: {zip_path!r}")
    dest = os.path.normpath(str(dest_dir or "").strip() or campplus_install_dir())
    os.makedirs(dest, exist_ok=True)
    onnx_name = ""
    data_name = ""
    with zipfile.ZipFile(source, "r") as handle:
        names = [item for item in handle.namelist() if not item.endswith("/")]
        for name in names:
            base = os.path.basename(name).lower()
            if base == "campplus.onnx":
                onnx_name = name
            elif base == "campplus.onnx.data":
                data_name = name
        if not onnx_name:
            raise FileNotFoundError("zip is missing campplus.onnx")
        onnx_dest = os.path.join(dest, "campplus.onnx")
        data_dest = os.path.join(dest, "campplus.onnx.data")
        with handle.open(onnx_name) as src, open(onnx_dest, "wb") as out:
            shutil.copyfileobj(src, out)
        if data_name:
            with handle.open(data_name) as src, open(data_dest, "wb") as out:
                shutil.copyfileobj(src, out)
    if not _is_ready_onnx(onnx_dest):
        raise RuntimeError("CAM++ extract is incomplete (missing campplus.onnx.data)")
    return onnx_dest


class CampplusOnnxEngine:
    def __init__(self, model_path: str, *, intra_op_num_threads: int = 2) -> None:
        path = os.path.normpath(os.path.abspath(str(model_path)))
        if not _is_ready_onnx(path):
            raise FileNotFoundError(f"CAM++ model not found: {path}")
        self.model_path = path
        options = build_session_options(prefer_gpu=False)
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = max(1, int(intra_op_num_threads))
        self._run_lock = threading.RLock()
        self._session = ort.InferenceSession(
            path,
            sess_options=options,
            providers=resolve_onnx_providers(prefer_gpu=False),
        )
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        if not inputs or not outputs:
            raise RuntimeError("CAM++ ONNX is missing inputs/outputs")
        self._input_name = str(inputs[0].name)
        self._output_name = str(outputs[0].name)

    def embed_fbank(self, features: np.ndarray) -> np.ndarray:
        feat = np.asarray(features, dtype=np.float32)
        if feat.ndim == 2:
            feat = feat[np.newaxis, :, :]
        if feat.ndim != 3 or feat.shape[-1] != 80:
            raise ValueError(f"CAM++ expects [batch, frames, 80], got {tuple(feat.shape)}")
        if feat.shape[1] <= 0:
            return np.zeros((feat.shape[0], EMBEDDING_DIM), dtype=np.float32)
        with self._run_lock:
            raw = self._session.run([self._output_name], {self._input_name: feat})[0]
        out = np.asarray(raw, dtype=np.float32)
        if out.ndim == 1:
            out = out.reshape(1, -1)
        return out

    def embed_waveform(self, waveform: np.ndarray, *, sample_rate: int = DEFAULT_SAMPLE_RATE) -> np.ndarray:
        feat = compute_fbank(waveform, sample_rate=int(sample_rate))
        if feat.shape[0] <= 0:
            return np.zeros((EMBEDDING_DIM,), dtype=np.float32)
        return self.embed_fbank(feat)[0]


def get_campplus_engine(
    *,
    explicit_path: str | None = None,
    model_dir: str | None = None,
) -> CampplusOnnxEngine:
    path = resolve_campplus_model_path(explicit_path=explicit_path, model_dir=model_dir)
    if not path:
        raise FileNotFoundError(
            "CAM++ model not found. Place campplus.onnx and campplus.onnx.data "
            "under resources/asr or models/campplus."
        )
    with _ENGINE_LOCK:
        engine = _ENGINE_CACHE.get(path)
        if engine is None:
            engine = CampplusOnnxEngine(path)
            _ENGINE_CACHE[path] = engine
        return engine
