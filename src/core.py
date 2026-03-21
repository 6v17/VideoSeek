import numpy as np
from src.update_video import update_videos
from src.clip_embedding import get_clip_embeddings_batch, get_text_embedding
from src.faiss_index import search_vector


def run_search(video_folder, query_data, is_text=False):
    # 1. 更新/加载 视频库索引
    all_vectors, all_timestamps, all_video_paths, cross_index = update_videos(video_folder)
    if cross_index is None:
        return []

    # 2. 生成搜索向量
    if is_text:
        query_vec = get_text_embedding(query_data)
    else:
        query_vec = get_clip_embeddings_batch([query_data])

        # 【修复】确保搜索向量是标准长度，否则相似度会乱跳
    query_vec = query_vec / (np.linalg.norm(query_vec, axis=1, keepdims=True) + 1e-10)

    matched = search_vector(query_vec, cross_index, all_timestamps, all_video_paths, top_k=10)
    return matched