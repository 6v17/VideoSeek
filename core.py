import base64
import os
import json
import hashlib
import numpy as np
from src.extract_frames import extract_frames_with_ffmpeg
from src.clip_embedding import get_clip_embeddings_batch
from src.faiss_index import create_clip_index, save_vectors, load_clip_index, search_vector,load_vectors
from src.utils import measure_time

META_FILE = "data/meta.json"
VECTOR_DIR = "data/vector"
INDEX_DIR = "data/index"
CROSS_INDEX_FILE = "data/global/cross_video_index.faiss"
CROSS_VECTOR_FILE = "data/global/cross_video_vectors.npy"

import torch

def free_memory():
    """
    定期释放 GPU 内存
    """
    torch.cuda.empty_cache()
def ensure_folder_exists(file_path):
    folder = os.path.dirname(file_path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)


def load_meta():
    if os.path.exists(META_FILE):
        with open(META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_meta(meta):
    ensure_folder_exists(META_FILE)
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4, ensure_ascii=False)


def get_video_hash(video_path):
    h = hashlib.sha256()
    with open(video_path, "rb") as f:
        chunk = f.read(10 * 1024 * 1024)
        h.update(chunk)
    return h.hexdigest()


# 向量生成
@measure_time("生成向量耗时：")
def generate_vectors_and_index_for_video(
    video_path,
    video_name,
    index_dir="data/index",
    vector_dir="data/vector"
):
    frames, timestamps = extract_frames_with_ffmpeg(video_path)

    if len(frames) == 0:
        print(f"No frames extracted for {video_name}")
        return [], [], None

    # 使用并行方式处理 CLIP 特征
    vectors = get_clip_embeddings_batch(frames, batch_size=32)
    free_memory()  # 清理 GPU 内存

    safe_video_name = base64.urlsafe_b64encode(video_name.encode()).decode()
    print(f"Safe video name for vector file: {safe_video_name}")

    vector_file = os.path.join(vector_dir, f"{safe_video_name}_vectors.npy")
    ensure_folder_exists(vector_file)
    print(f"Saving vectors to {vector_file}")
    save_vectors(vectors, timestamps, vector_file)

    index_file = os.path.join(index_dir, f"{safe_video_name}_index.faiss")
    ensure_folder_exists(index_file)
    index = create_clip_index(vectors, index_file)

    return vectors, timestamps, index
#safe_name = base64.urlsafe_b64encode(video_name.encode()).decode()
def update_videos(video_folder):
    meta = load_meta()
    all_vectors = []
    all_timestamps = []
    all_video_paths = []

    for video_file in os.listdir(video_folder):
        video_path = os.path.join(video_folder, video_file)
        if not os.path.isfile(video_path) or not video_file.endswith(('.mp4', '.mkv', '.avi', '.mov')):
            continue

        video_hash = get_video_hash(video_path)
        video_mod_time = os.path.getmtime(video_path)
        saved = meta.get(video_file, {})

        # 判断是否需要重新生成
        if saved.get("hash") == video_hash and saved.get("mod_time") == video_mod_time:
            safe_name = base64.urlsafe_b64encode(video_file.encode()).decode()
            vector_file = os.path.join(VECTOR_DIR, f"{safe_name}_vectors.npy")
            print(f"Loading vectors from {vector_file}")
            data = load_vectors(vector_file)
            if data is None:
                print(f"Error loading vectors for {video_file}")
                continue
            vectors = data['vector']
            timestamps = data['timestamps']
        else:
            vectors, timestamps, _ = generate_vectors_and_index_for_video(video_path, video_file)
            meta[video_file] = {"hash": video_hash, "mod_time": video_mod_time}

        if len(vectors) > 0:
            all_vectors.append(vectors)
            all_timestamps.extend(timestamps)
            all_video_paths.extend([video_path] * len(timestamps))

    save_meta(meta)

    if len(all_vectors) == 0:
        return None, None, None, None

    all_vectors = np.vstack(all_vectors)
    all_timestamps = np.array(all_timestamps)
    all_video_paths = np.array(all_video_paths)

    # 生成跨视频索引
    cross_index = create_clip_index(all_vectors, CROSS_INDEX_FILE)

    # 这里修改为正确的 save_vectors 调用
    save_vectors(all_vectors, all_timestamps, output_file=CROSS_VECTOR_FILE)

    return all_vectors, all_timestamps, all_video_paths, cross_index


if __name__ == "__main__":
    video_folder = r"C:\Users\LiuWei\Desktop\video"

    all_vectors, all_timestamps, all_video_paths, cross_index = update_videos(video_folder)

    # 查询示例
    query_image_path = "img/img_3.png"
    query_vector = get_clip_embeddings_batch(query_image_path)
    fps = 30  # 可用 cv2 获取实际 fps
    matched = search_vector(query_vector, cross_index, all_timestamps, all_video_paths, fps)

    for timestamp, sec, similarity, video_path in matched:
        print(f"视频: {video_path}, 时间: {sec:.2f}s, 相似度: {similarity:.3f}")