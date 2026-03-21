import base64
import os
import numpy as np
from src.clip_embedding import generate_vectors_and_index_for_video
from src.faiss_index import create_clip_index, save_vectors, load_vectors
from src.utils import save_meta, load_meta, get_video_hash, ensure_folder_exists
from src.config import load_config


# --- 确保这几个函数名存在，供 Worker 调用 ---

def get_video_files(video_folder):
    video_files = []
    for f in os.listdir(video_folder):
        p = os.path.join(video_folder, f)
        if os.path.isfile(p) and f.lower().endswith(('.mp4', '.mkv', '.avi', '.mov')):
            video_files.append((f, p))
    return video_files


def process_single_video(video_path, video_file, meta, config):
    video_hash = get_video_hash(video_path)
    video_mod_time = os.path.getmtime(video_path)
    saved = meta.get(video_file, {})

    # 检查是否需要更新
    if saved.get("hash") == video_hash and saved.get("mod_time") == video_mod_time:
        # 尝试加载旧向量
        vectors, timestamps = load_video_vectors(video_file, config)
        if vectors is not None:
            return vectors, timestamps

    # 确实需要生成
    vectors, timestamps, _ = generate_vectors_and_index_for_video(
        video_path, video_file, config["index_dir"], config["vector_dir"]
    )
    meta[video_file] = {"hash": video_hash, "mod_time": video_mod_time}
    return vectors, timestamps


def load_video_vectors(video_file, config):
    safe_name = base64.urlsafe_b64encode(video_file.encode()).decode()
    vector_file = os.path.join(config["vector_dir"], f"{safe_name}_vectors.npy")

    # 核心：np.load 会返回一个包含字典的 ndarray
    data = load_vectors(vector_file)

    # 【最关键的修复】：确保返回的是 numpy 数组，而不是字典本身
    if data is not None and isinstance(data, dict):
        return data.get('vector'), data.get('timestamps')

    return None, None


def merge_and_save_all_vectors(all_vectors, all_timestamps, all_video_paths, config):
    if not all_vectors: return None
    all_v = np.vstack(all_vectors)
    all_t = np.array(all_timestamps)
    all_p = np.array(all_video_paths)
    ensure_folder_exists(config["cross_index_file"])
    create_clip_index(all_v, config["cross_index_file"])
    save_vectors(all_v, all_t, config["cross_vector_file"])
    return True


def update_videos(video_folder):
    """搜索时调用的老接口：逻辑不变"""
    config = load_config()
    meta = load_meta(config["meta_file"])
    video_files = get_video_files(video_folder)
    all_v, all_t, all_p = [], [], []
    for f, p in video_files:
        v, t = process_single_video(p, f, meta, config)
        if v is not None:
            all_v.append(v)
            all_t.extend(t)
            all_p.extend([p] * len(t))
    save_meta(meta, config["meta_file"])
    merge_and_save_all_vectors(all_v, all_t, all_p, config)
    # 返回搜索需要的数据
    from src.faiss_index import load_clip_index
    return np.vstack(all_v), np.array(all_t), np.array(all_p), load_clip_index(config["cross_index_file"])