import base64
import os
import numpy as np


from src.clip_embedding import generate_vectors_and_index_for_video
from src.faiss_index import create_clip_index, save_vectors, load_vectors
from src.utils import save_meta, load_meta, get_video_hash, ensure_folder_exists
from src.config import load_config  # 导入配置文件加载函数

def get_video_metadata(video_file, video_path, meta):
    """
    获取视频的元数据（哈希值、修改时间），并判断是否需要重新生成。
    :param video_file: 视频文件名
    :param video_path: 视频文件路径
    :param meta: 存储视频元数据的字典
    :return: 哈希值、修改时间、是否需要重新生成
    """
    video_hash = get_video_hash(video_path)
    video_mod_time = os.path.getmtime(video_path)
    saved = meta.get(video_file, {})

    # 判断是否需要重新生成
    need_to_generate = saved.get("hash") != video_hash or saved.get("mod_time") != video_mod_time

    return video_hash, video_mod_time, need_to_generate


def load_video_vectors(video_file, config):
    """
    加载已保存的向量和时间戳
    :param video_file: 视频文件名
    :param config: 配置信息，包含了目录路径
    :return: 向量和时间戳，或者 None 如果加载失败
    """
    ensure_folder_exists(config["vector_dir"])
    safe_name = base64.urlsafe_b64encode(video_file.encode()).decode()
    vector_file = os.path.join(config["vector_dir"], f"{safe_name}_vectors.npy")
    print(f"Loading vectors from {vector_file}")

    try:
        data = load_vectors(vector_file)
    except Exception as e:
        print(f"Error loading vectors for {video_file}: {e}")
        return None, None
    if data is None:
        print(f"No vectors found for {video_file}")
        return None, None
    return data['vector'], data['timestamps']


def process_video(video_path, video_file, meta, config):
    """
    处理视频生成新向量和索引，或者加载已有的向量。
    :param video_path: 视频路径
    :param video_file: 视频文件名
    :param meta: 存储视频元数据的字典
    :param config: 配置信息，包含了目录路径
    :return: 向量、时间戳
    """
    video_hash, video_mod_time, need_to_generate = get_video_metadata(video_file, video_path, meta)

    if not need_to_generate:
        vectors, timestamps = load_video_vectors(video_file, config)
    else:
        ensure_folder_exists(config["vector_dir"])
        ensure_folder_exists(config["index_dir"])
        # 修正传递的路径参数
        vectors, timestamps, _ = generate_vectors_and_index_for_video(video_path, video_file,
                                                                      index_dir=config["index_dir"],  # 传递正确的路径
                                                                      vector_dir=config["vector_dir"])  # 同理传递其他路径
        meta[video_file] = {"hash": video_hash, "mod_time": video_mod_time}

    return vectors, timestamps


def get_video_files(video_folder):
    """
    获取视频文件夹中的所有视频文件，过滤非视频文件。
    :param video_folder: 视频文件夹路径
    :return: 视频文件路径列表
    """
    video_files = []
    for video_file in os.listdir(video_folder):
        video_path = os.path.join(video_folder, video_file)
        if os.path.isfile(video_path) and video_file.endswith(('.mp4', '.mkv', '.avi', '.mov')):
            video_files.append((video_file, video_path))
    return video_files

def process_video_for_folder(video_file, video_path, meta, config):
    """
    处理单个视频，获取向量和时间戳，或者加载已有的向量。
    :param video_file: 视频文件名
    :param video_path: 视频文件路径
    :param meta: 存储视频元数据的字典
    :param config: 配置信息，包含了目录路径
    :return: 向量、时间戳
    """
    video_hash, video_mod_time, need_to_generate = get_video_metadata(video_file, video_path, meta)

    if not need_to_generate:
        vectors, timestamps = load_video_vectors(video_file, config)
    else:
        ensure_folder_exists(config["vector_dir"])
        ensure_folder_exists(config["index_dir"])
        vectors, timestamps, _ = generate_vectors_and_index_for_video(video_path, video_file, config["index_dir"], vector_dir=config["vector_dir"])
        meta[video_file] = {"hash": video_hash, "mod_time": video_mod_time}

    return vectors, timestamps

def update_meta(meta, config):
    """
    保存更新后的meta数据
    :param meta: 存储视频元数据的字典
    :param config: 配置信息，包含了目录路径
    """
    save_meta(meta, config["meta_file"])  # 使用配置路径

def merge_and_save_all_vectors(all_vectors, all_timestamps, all_video_paths, config):
    """
    合并所有视频的向量和时间戳，并保存到文件。
    :param all_vectors: 所有视频的向量
    :param all_timestamps: 所有视频的时间戳
    :param all_video_paths: 所有视频路径
    :param config: 配置信息，包含了目录路径
    :return: 合并后的向量、时间戳、路径和跨视频索引
    """
    if len(all_vectors) == 0:
        return None, None, None, None

    all_vectors = np.vstack(all_vectors)
    all_timestamps = np.array(all_timestamps)
    all_video_paths = np.array(all_video_paths)
    # 确保目录存在
    ensure_folder_exists(config["cross_index_file"])
    ensure_folder_exists(config["cross_vector_file"])
    # 生成跨视频索引
    cross_index = create_clip_index(all_vectors, config["cross_index_file"])  # 使用配置路径

    # 保存所有向量和时间戳
    save_vectors(all_vectors, all_timestamps, output_file=config["cross_vector_file"])  # 使用配置路径

    return all_vectors, all_timestamps, all_video_paths, cross_index

def update_videos(video_folder):
    """
    更新所有视频的向量和索引，或者重新生成向量。
    :param video_folder: 视频文件夹路径
    :return: 所有视频的向量、时间戳、视频路径和跨视频索引
    """
    config = load_config()  # 从配置文件加载路径
    meta = load_meta(config["meta_file"])  # 使用配置路径

    all_vectors = []
    all_timestamps = []
    all_video_paths = []

    # 获取视频文件列表
    video_files = get_video_files(video_folder)

    for video_file, video_path in video_files:
        # 处理视频，获取向量和时间戳
        vectors, timestamps = process_video_for_folder(video_file, video_path, meta, config)

        if len(vectors) > 0:
            all_vectors.append(vectors)
            all_timestamps.extend(timestamps)
            all_video_paths.extend([video_path] * len(timestamps))

    # 更新元数据
    update_meta(meta, config)

    # 合并并保存所有视频的向量和时间戳
    return merge_and_save_all_vectors(all_vectors, all_timestamps, all_video_paths, config)