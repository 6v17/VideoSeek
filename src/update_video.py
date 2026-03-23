import base64
import os
import numpy as np
from src.clip_embedding import generate_vectors_and_index_for_video
from src.faiss_index import create_clip_index, save_vectors, load_vectors
from src.utils import save_meta, load_meta, get_video_hash, ensure_folder_exists
from src.config import load_config


def get_video_files(video_folder):
    video_files = []
    # 使用 os.walk 进行深遍历
    for root, dirs, files in os.walk(video_folder):
        for f in files:
            if f.lower().endswith(('.mp4', '.mkv', '.avi', '.mov')):
                abs_path = os.path.join(root, f)
                # 计算相对路径，例如: "Action/01.mp4"
                rel_path = os.path.relpath(str(abs_path), video_folder)
                video_files.append((rel_path, abs_path))
    return video_files

#检查视频库下是否有文件变动，有则增量更新向量，少则删除向量
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
    #返回向量、时间
    return vectors, timestamps

#加载已存在向量
def load_video_vectors(video_file, config):
    safe_name = base64.urlsafe_b64encode(video_file.encode()).decode()
    vector_file = os.path.join(config["vector_dir"], f"{safe_name}_vectors.npy")

    # 核心：np.load 会返回一个包含字典的 ndarray
    data = load_vectors(vector_file)

    # 【最关键的修复】：确保返回的是 numpy 数组，而不是字典本身
    if data is not None and isinstance(data, dict):
        return data.get('vector'), data.get('timestamps')

    return None, None

#生成总索引
def merge_and_save_all_vectors(all_vectors, all_timestamps, all_video_paths, config):
    # 修复：使用 is None 判断，因为 all_vectors 可能是 ndarray
    if all_vectors is None:
        return None

    # 修复：如果是列表则合并，如果是已经合并好的数组则跳过 vstack
    if isinstance(all_vectors, list):
        if len(all_vectors) == 0: return None
        all_v = np.vstack(all_vectors)
    else:
        all_v = all_vectors

    all_t = np.array(all_timestamps)
    ensure_folder_exists(config["cross_index_file"])

    create_clip_index(all_v, config["cross_index_file"])
    save_vectors(all_v, all_t, config["cross_vector_file"])
    return True

def sync_meta_with_disk(video_folder, meta):
    """同步磁盘文件与 meta 记录，返回当前存在的视频列表"""
    current_videos = []
    current_rel_paths = set()

    # 1. 扫描磁盘
    for root, _, files in os.walk(video_folder):
        for f in files:
            if f.lower().endswith(('.mp4', '.mkv', '.avi', '.mov')):
                abs_path = os.path.join(root, f)
                rel_path = os.path.relpath(str(abs_path), str(video_folder))
                current_videos.append((rel_path, abs_path))
                current_rel_paths.add(rel_path)

    # 2. 清理 meta 中已失效的记录 (视频被删除了)
    deleted_keys = [k for k in meta.keys() if k not in current_rel_paths]
    for k in deleted_keys:
        print(f"Cleanup: Removing deleted video from meta: {k}")
        del meta[k]
        # 如果有物理缓存文件，也可以在这里 os.remove

    return current_videos


def collect_active_vectors(video_files, meta, config):
    """处理视频并汇总所有向量、时间轴和路径"""
    all_v, all_t, all_p = [], [], []

    for rel_path, abs_path in video_files:
        # 注意：这里 meta 的 key 传入的是 rel_path
        v, t = process_single_video(abs_path, rel_path, meta, config)

        if v is not None and len(v) > 0:
            all_v.append(v)
            all_t.extend(t)
            # 建议存储 abs_path 以便播放器直接打开
            all_p.extend([abs_path] * len(t))

    if not all_v:
        return None, None, None

    return np.vstack(all_v), np.array(all_t), np.array(all_p)


def update_videos(video_folder):
    """搜索时调用的主接口"""
    # 1. 环境准备
    config = load_config()
    meta = load_meta(config["meta_file"])

    # 2. 同步磁盘与 Meta (处理删除逻辑)
    video_files = sync_meta_with_disk(video_folder, meta)

    # 3. 处理/加载向量 (处理新增与更新逻辑)
    v_stack, t_array, p_array = collect_active_vectors(video_files, meta, config)

    if v_stack is None:
        print("No video vectors found.")
        return None, None, None, None

    # 4. 持久化
    save_meta(meta, config["meta_file"])
    merge_and_save_all_vectors(v_stack, t_array, p_array, config)

    # 5. 加载索引并返回
    from src.faiss_index import load_clip_index
    index = load_clip_index(config["cross_index_file"])

    return v_stack, t_array, p_array, index