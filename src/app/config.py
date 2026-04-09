import json
import os

from src.app.app_meta import get_app_meta
from src.app.logging_utils import get_logger
from src.utils import get_default_model_dir, get_resource_path

CONFIG_FILE = get_resource_path("config.json")
logger = get_logger("config")

DEFAULT_CONFIG = {
    "fps": 1,
    "search_top_k": 20,
    "preview_seconds": 6,
    "preview_width": 640,
    "preview_height": 360,
    "thumb_width": 130,
    "thumb_height": 75,
    "prefer_gpu": True,
    "similarity_threshold": 0.85,
    "max_chunk_duration": 5.0,
    "min_chunk_size": 2,
    "chunk_similarity_mode": "chunk",
    "search_mode": "frame",
    "ffmpeg_path": "",
    "model_dir": get_default_model_dir(),
    "meta_file": "data/meta.json",
    "vector_dir": "data/vector",
    "index_dir": "data/index",
    "cross_index_file": "data/global/cross_video_index.faiss",
    "cross_vector_file": "data/global/cross_video_vectors.npy",
    "cross_chunk_index_file": "data/global/cross_chunk_index.faiss",
    "cross_chunk_vector_file": "data/global/cross_chunk_vectors.npy",
    "remote_index_file": "data/remote/remote_index.faiss",
    "remote_vector_file": "data/remote/remote_vectors.npy",
    "remote_max_frames": 2000,
    "theme": "dark",
    "language": "zh",
}

def get_app_version():
    return str(get_app_meta().get("version", "1.0.0"))


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
            config = json.load(handle)
        for key, value in DEFAULT_CONFIG.items():
            config.setdefault(key, value)
        # Migrate legacy cap from old builds; 300 causes long videos to look capped at ~299s.
        try:
            if int(config.get("remote_max_frames", 0)) == 300:
                config["remote_max_frames"] = DEFAULT_CONFIG["remote_max_frames"]
        except Exception:
            config["remote_max_frames"] = DEFAULT_CONFIG["remote_max_frames"]
        return config

    logger.info("Config file %s not found, using default values", CONFIG_FILE)
    return DEFAULT_CONFIG.copy()


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=4, ensure_ascii=False)
