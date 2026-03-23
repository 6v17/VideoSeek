import json
import os

from src.utils import get_resource_path

CONFIG_FILE = get_resource_path("config.json") # 配置文件路径

def load_config():
    """
    加载配置文件。
    :return: 返回配置字典。
    """
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            # 确保一些关键路径存在，防止代码报错
            # 如果没有这些 key，给个默认值
            defaults = {
                "fps": 1,
                "meta_file": "data/meta.json",
                "vector_dir": "data/vector",
                "index_dir": "data/index",
                "cross_index_file": "data/global/cross_video_index.faiss",
                "cross_vector_file": "data/global/cross_video_vectors.npy"
            }
            for k, v in defaults.items():
                if k not in cfg: cfg[k] = v
            return cfg
    else:
        print(f"Config file {CONFIG_FILE} not found, using default values.")
        return {
            "meta_file": "data/meta.json",
            "vector_dir": "data/vector",
            "index_dir": "data/index",
            "cross_index_file": "data/global/cross_video_index.faiss",
            "cross_vector_file": "data/global/cross_video_vectors.npy",
            "fps":1
        }

def save_config(config):
    """
    保存配置到文件。
    :param config: 配置字典
    """
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)