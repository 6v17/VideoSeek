import contextlib
import os
import shutil
import sys

import faiss
import numpy as np
import tempfile

from src.app.logging_utils import get_logger
from src.core.semantic_chunking import pack_chunks
from src.utils import measure_time

logger = get_logger("faiss_index")

_FAISS_STAGING_ROOT = None


def _path_has_non_ascii(path):
    try:
        os.fspath(path).encode("ascii")
    except UnicodeEncodeError:
        return True
    return False


def _faiss_io_needs_ascii_staging(path):
    """FAISS C++ file IO on Windows often fails for non-ASCII paths."""
    return sys.platform == "win32" and _path_has_non_ascii(path)


def _resolve_faiss_ascii_staging_root():
    """Return a writable ASCII-only directory for FAISS C++ staging on Windows."""
    global _FAISS_STAGING_ROOT
    if _FAISS_STAGING_ROOT is not None:
        return _FAISS_STAGING_ROOT

    candidates = []
    program_data = os.environ.get("PROGRAMDATA", "")
    if program_data:
        candidates.append(os.path.join(program_data, "VideoSeek", "faiss-io"))
    system_drive = os.environ.get("SystemDrive", "")
    if system_drive:
        candidates.append(os.path.join(system_drive + os.sep, "Temp", "VideoSeek", "faiss-io"))
    candidates.append(os.path.join("C:", os.sep, "VideoSeek", "faiss-io"))

    for candidate in candidates:
        normalized = os.path.normpath(candidate)
        if _path_has_non_ascii(normalized):
            continue
        try:
            os.makedirs(normalized, exist_ok=True)
            _FAISS_STAGING_ROOT = normalized
            return normalized
        except OSError as exc:
            logger.debug("FAISS staging root unavailable at %s: %s", normalized, exc)

    raise OSError("No writable ASCII path available for FAISS index staging")


@contextlib.contextmanager
def _faiss_ascii_stage_dir():
    """Create a per-operation ASCII staging directory and remove it on exit."""
    with tempfile.TemporaryDirectory(prefix="vs_faiss_", dir=_resolve_faiss_ascii_staging_root()) as stage_dir:
        yield stage_dir


def _paths_on_same_drive(path_a, path_b):
    return os.path.normcase(os.path.splitdrive(path_a)[0]) == os.path.normcase(os.path.splitdrive(path_b)[0])


def _commit_temp_file(temp_path, target_file):
    """Move or copy a finished temp file to its final path (Windows cannot replace across drives)."""
    if os.path.normcase(temp_path) == os.path.normcase(target_file):
        return
    if _paths_on_same_drive(temp_path, target_file):
        os.replace(temp_path, target_file)
        return
    shutil.copy2(temp_path, target_file)
    os.remove(temp_path)


def _write_faiss_index_via_temp(index, index_file, stage_dir):
    fd, temp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".faiss", dir=stage_dir)
    os.close(fd)
    try:
        faiss.write_index(index, temp_path)
        _commit_temp_file(temp_path, index_file)
        temp_path = ""
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def _atomic_write_faiss_index(index, index_file):
    folder = os.path.dirname(index_file)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if _faiss_io_needs_ascii_staging(index_file):
        logger.debug("Staging FAISS index write via ASCII temp for path: %s", index_file)
        with _faiss_ascii_stage_dir() as stage_dir:
            _write_faiss_index_via_temp(index, index_file, stage_dir)
        return
    _write_faiss_index_via_temp(index, index_file, folder or None)


def _atomic_save_npy(output_file, data):
    folder = os.path.dirname(output_file)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".npy", dir=folder or None)
    os.close(fd)
    actual_temp_path = temp_path if temp_path.endswith(".npy") else f"{temp_path}.npy"
    try:
        np.save(temp_path, data)
        os.replace(actual_temp_path, output_file)
    finally:
        for path in [temp_path, actual_temp_path]:
            if os.path.exists(path):
                os.remove(path)


def atomic_save_numpy(output_file, data):
    _atomic_save_npy(output_file, data)


def _normalize_vectors(vectors):
    vectors = np.asarray(vectors, dtype="float32")
    if vectors.ndim == 1:
        vectors = vectors.reshape(1, -1)
    if vectors.size == 0:
        return vectors
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-10)


class IncrementalClipIndex:
    """Build a FAISS index one video/batch at a time to limit peak memory."""

    def __init__(self):
        self._index = None
        self._total = 0

    @property
    def total(self):
        return self._total

    def add(self, vectors_list):
        vectors = _normalize_vectors(vectors_list)
        if vectors.size == 0:
            return 0
        if self._index is None:
            self._index = faiss.IndexFlatIP(int(vectors.shape[1]))
        self._index.add(vectors)
        added = int(vectors.shape[0])
        self._total += added
        return added

    def save(self, index_file):
        if self._index is None or self._total <= 0:
            raise ValueError("Cannot save an empty incremental index")
        _atomic_write_faiss_index(self._index, index_file)
        logger.info("Index saved to %s (%s vectors)", index_file, self._total)
        return self._index


@measure_time("Index build time:")
def create_clip_index(vectors_list, index_file, *, prefer_gpu=False):
    vectors = _normalize_vectors(vectors_list)
    if prefer_gpu and faiss_gpu_available():
        return _create_clip_index_gpu(vectors, index_file)
    builder = IncrementalClipIndex()
    builder.add(vectors)
    return builder.save(index_file)


def faiss_gpu_available(*, force_refresh=False):
    try:
        from src.core.gpu_vector_ops import faiss_gpu_available as _probe

        return _probe(force_refresh=force_refresh)
    except Exception:
        return False


def _create_clip_index_gpu(vectors, index_file):
    import faiss

    vectors = np.ascontiguousarray(np.asarray(vectors, dtype=np.float32))
    if vectors.size == 0:
        raise ValueError("Cannot build an empty GPU FAISS index")
    dim = int(vectors.shape[1])
    resources = faiss.StandardGpuResources()
    gpu_index = faiss.GpuIndexFlatIP(resources, dim)
    gpu_index.add(vectors)
    cpu_index = faiss.index_gpu_to_cpu(gpu_index)
    _atomic_write_faiss_index(cpu_index, index_file)
    logger.info("GPU FAISS index saved to %s (%s vectors)", index_file, int(vectors.shape[0]))
    return cpu_index


def load_clip_index(index_file):
    if not os.path.exists(index_file):
        return None
    if not _faiss_io_needs_ascii_staging(index_file):
        return faiss.read_index(index_file)
    with _faiss_ascii_stage_dir() as stage_dir:
        fd, temp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".faiss", dir=stage_dir)
        os.close(fd)
        try:
            shutil.copy2(index_file, temp_path)
            return faiss.read_index(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


def search_vector(query_vector, index, timestamps, video_paths, top_k=10):
    actual_k = min(top_k, index.ntotal)
    if actual_k <= 0:
        return []

    distances, indices = index.search(query_vector, actual_k)
    matched_results = []
    for rank, index_value in enumerate(indices[0]):
        if index_value == -1 or index_value >= len(video_paths):
            continue
        timestamp = timestamps[index_value]
        video_path = video_paths[index_value]
        matched_results.append((timestamp, timestamp, distances[0][rank], video_path))
    return matched_results


def save_vectors(vectors_list, timestamps, output_file, chunks=None, chunk_config=None, embedding_spec=None):
    folder_path = os.path.dirname(output_file)
    if folder_path and not os.path.exists(folder_path):
        os.makedirs(folder_path)

    data = {
        "vector": np.asarray(vectors_list, dtype="float32"),
        "timestamps": np.asarray(timestamps, dtype="float32"),
    }
    chunk_payload = pack_chunks(chunks or [])
    if chunk_payload is not None:
        data["chunks"] = chunk_payload
    if isinstance(chunk_config, dict):
        data["chunk_config"] = chunk_config
    if isinstance(embedding_spec, dict):
        data["embedding_spec"] = dict(embedding_spec)
    _atomic_save_npy(output_file, data)
    logger.info("Vectors saved to %s", output_file)
    return data


def load_vectors(input_file):
    if os.path.exists(input_file):
        return np.load(input_file, allow_pickle=True).item()

    logger.warning("Vector file not found: %s", input_file)
    return None
