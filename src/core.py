# src/core.py
import cv2
import faiss
import numpy as np
import os  # 新增
from src.config import load_config  # 新增：修复报错的关键
from src.clip_embedding import get_clip_embeddings_batch, get_text_embedding


# 进行查帧
def run_search(query_data, is_text=False):
    config = load_config()

    # 路径检查：如果全局索引文件不存在，说明还没同步过
    if not os.path.exists(config["cross_index_file"]) or not os.path.exists(config["cross_vector_file"]):
        print("错误：全局索引文件不存在，请先点击“更新全量索引”")
        return []

    # 加载已有的全局索引
    from src.faiss_index import load_clip_index
    cross_index = load_clip_index(config["cross_index_file"])

    # 加载全局向量数据
    try:
        data = np.load(config["cross_vector_file"], allow_pickle=True).item()
        all_timestamps = data['timestamps']
        all_video_paths = data['paths']
    except Exception as e:
        print(f"加载向量文件失败: {e}")
        return []

    if cross_index is None:
        return []

    # 推理逻辑
    if is_text:
        query_vec = get_text_embedding(query_data)
    else:
        if isinstance(query_data, str):
            # 支持中文路径读取图片
            img = cv2.imdecode(np.fromfile(query_data, dtype=np.uint8), cv2.IMREAD_COLOR)
            query_vec = get_clip_embeddings_batch([img])
        else:
            query_vec = get_clip_embeddings_batch([query_data])

    query_vec = query_vec.astype("float32")
    faiss.normalize_L2(query_vec)

    from src.faiss_index import search_vector
    # 搜索 Top 100 结果
    return search_vector(query_vec, cross_index, all_timestamps, all_video_paths, top_k=20)