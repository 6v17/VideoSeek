import os

import numpy as np

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.core.faiss_index import load_clip_index
from src.services.search_service import build_query_vector

logger = get_logger("remote_search_service")


def load_remote_search_assets(config):
    index_file = config.get("remote_index_file", "")
    vector_file = config.get("remote_vector_file", "")
    if not index_file or not vector_file or not os.path.exists(index_file) or not os.path.exists(vector_file):
        return None

    search_index = load_clip_index(index_file)
    if search_index is None:
        return None

    try:
        data = np.load(vector_file, allow_pickle=True).item()
    except Exception:
        return None

    return {
        "index": search_index,
        "timestamps": data.get("timestamps"),
        "source_links": data.get("source_links"),
        "titles": data.get("titles"),
        "paths": data.get("paths"),
    }


def run_remote_search(query_data, is_text=True, top_k=None):
    config = load_config()
    if top_k is None:
        top_k = int(config.get("search_top_k", 20))
    assets = load_remote_search_assets(config)
    if not assets:
        return []

    query_vector = build_query_vector(query_data, is_text=is_text)
    index = assets["index"]
    actual_k = min(int(top_k), int(index.ntotal))
    if actual_k <= 0:
        return []

    distances, indices = index.search(query_vector, actual_k)
    timestamps = assets["timestamps"]
    source_links = assets["source_links"]
    titles = assets["titles"]
    paths = assets["paths"]

    results = []
    for rank, idx in enumerate(indices[0]):
        item_index = int(idx)
        if item_index < 0:
            continue
        start_sec = _value_at(timestamps, item_index, default=0.0)
        source_link = _value_at(source_links, item_index, default="")
        title = _value_at(titles, item_index, default="")
        if not title:
            title = os.path.basename(_value_at(paths, item_index, default=f"remote_{item_index}"))
        results.append(
            {
                "title": str(title),
                "time_sec": float(start_sec),
                "score": float(distances[0][rank]),
                "source_link": str(source_link),
            }
        )
    return results


def _value_at(items, index, default=""):
    if isinstance(items, (list, np.ndarray)) and 0 <= index < len(items):
        return items[index]
    return default
