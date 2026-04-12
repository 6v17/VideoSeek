import os

import faiss
import numpy as np
import tempfile

from src.app.logging_utils import get_logger
from src.core.semantic_chunking import pack_chunks
from src.utils import measure_time

logger = get_logger("faiss_index")


def _atomic_write_faiss_index(index, index_file):
    folder = os.path.dirname(index_file)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".faiss", dir=folder or None)
    os.close(fd)
    try:
        faiss.write_index(index, temp_path)
        os.replace(temp_path, index_file)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


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


@measure_time("Index build time:")
def create_clip_index(vectors_list, index_file):
    vectors = np.asarray(vectors_list, dtype="float32")
    vectors = np.asarray([
        vector / np.linalg.norm(vector) if np.linalg.norm(vector) != 0 else vector
        for vector in vectors
    ], dtype="float32")

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    _atomic_write_faiss_index(index, index_file)
    logger.info("Index saved to %s", index_file)
    return index


def load_clip_index(index_file):
    if os.path.exists(index_file):
        return faiss.read_index(index_file)
    return None


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


def save_vectors(vectors_list, timestamps, output_file, chunks=None, chunk_config=None):
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
    _atomic_save_npy(output_file, data)
    logger.info("Vectors saved to %s", output_file)
    return data


def load_vectors(input_file):
    if os.path.exists(input_file):
        return np.load(input_file, allow_pickle=True).item()

    logger.warning("Vector file not found: %s", input_file)
    return None
