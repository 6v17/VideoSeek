import json
import os

CONFIG_FILE = "config.json"  # 配置文件路径

def load_config():
    """
    加载配置文件。
    :return: 返回配置字典。
    """
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
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