import os

import cv2
import faiss
import numpy as np

from src.core.clip_embedding import get_clip_embeddings_batch, get_text_embedding
from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.core.faiss_index import load_clip_index, search_vector

logger = get_logger("search_service")


def load_search_assets(config):
    index_file = config["cross_index_file"]
    vector_file = config["cross_vector_file"]

    if not os.path.exists(index_file) or not os.path.exists(vector_file):
        logger.warning("Global frame search index is missing. Please update the index first.")
        return None, None, None

    search_index = load_clip_index(index_file)
    if search_index is None:
        return None, None, None

    try:
        data = np.load(vector_file, allow_pickle=True).item()
    except Exception as exc:
        logger.error("Failed to load frame search vectors: %s", exc)
        return None, None, None

    return search_index, data.get("timestamps"), data.get("paths")


def load_chunk_search_assets(config):
    index_file = config["cross_chunk_index_file"]
    vector_file = config["cross_chunk_vector_file"]

    if not os.path.exists(index_file) or not os.path.exists(vector_file):
        logger.warning("Global chunk search index is missing. Please update the index first.")
        return None, None, None

    search_index = load_clip_index(index_file)
    if search_index is None:
        return None, None, None

    try:
        data = np.load(vector_file, allow_pickle=True).item()
    except Exception as exc:
        logger.error("Failed to load chunk search vectors: %s", exc)
        return None, None, None

    return search_index, data.get("ranges"), data.get("paths")


def build_query_vector(query_data, is_text=False):
    if is_text:
        query_vector = get_text_embedding(query_data)
    elif isinstance(query_data, str):
        image = cv2.imdecode(np.fromfile(query_data, dtype=np.uint8), cv2.IMREAD_COLOR)
        query_vector = get_clip_embeddings_batch([image])
    else:
        query_vector = get_clip_embeddings_batch([query_data])

    query_vector = query_vector.astype("float32")
    faiss.normalize_L2(query_vector)
    return query_vector


def run_search(query_data, is_text=False, top_k=None):
    config = load_config()
    search_mode = config.get("search_mode", "frame")
    logger.info("Running %s search (is_text=%s)", search_mode, is_text)
    if search_mode == "chunk":
        return run_chunk_search(query_data, is_text=is_text, top_k=top_k)
    if top_k is None:
        top_k = config.get("search_top_k", 20)
    search_index, timestamps, video_paths = load_search_assets(config)
    if search_index is None:
        return []

    query_vector = build_query_vector(query_data, is_text=is_text)
    return search_vector(query_vector, search_index, timestamps, video_paths, top_k=top_k)


def run_chunk_search(query_data, is_text=False, top_k=None):
    config = load_config()
    if top_k is None:
        top_k = config.get("search_top_k", 20)
    search_index, ranges, video_paths = load_chunk_search_assets(config)
    if search_index is None:
        return []

    query_vector = build_query_vector(query_data, is_text=is_text)
    actual_k = min(top_k, search_index.ntotal)
    if actual_k <= 0:
        return []

    distances, indices = search_index.search(query_vector, actual_k)
    matched_results = []
    for rank, index_value in enumerate(indices[0]):
        if index_value == -1 or index_value >= len(video_paths):
            continue
        time_range = ranges[index_value]
        start_time = float(time_range[0])
        end_time = float(time_range[1])
        matched_results.append((start_time, end_time, distances[0][rank], video_paths[index_value]))
    return matched_results
