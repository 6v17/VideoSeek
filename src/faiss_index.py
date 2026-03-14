import faiss
import numpy as np
import os
def create_clip_index(vectors_list, index_file="video_index.faiss"):
    """
    创建 CLIP 向量的索引，并将索引保存到文件。
    :param vectors_list: CLIP 向量列表
    :param index_file: 索引保存路径
    :return: 创建的 FAISS 索引
    """
    vectors = np.array(vectors_list).astype("float32")

    # 创建 FAISS 索引（使用内积作为度量）
    index = faiss.IndexFlatIP(vectors.shape[1])

    # 向索引中添加向量
    index.add(vectors)

    # 保存索引
    faiss.write_index(index, index_file)
    print(f"Index saved to {index_file}")

    return index
def load_clip_index(index_file="video_index.faiss"):
    """
    加载已保存的 CLIP 向量索引
    :param index_file: 索引文件路径
    :return: 加载的 FAISS 索引
    """
    # 加载 FAISS 索引
    if os.path.exists(index_file):
        print(f"Loaded index from {index_file}")
        return faiss.read_index(index_file)
    else:
        print(f"Index file {index_file} not found.")
        return None
def search_vector(query_vector, index, timestamps, fps, top_k=5):
    """
    查询图像的 CLIP 向量并返回匹配的时间戳。
    :param query_vector: 查询图像的 CLIP 向量
    :param index: 已创建的 FAISS 索引
    :param timestamps: 所有帧的时间戳
    :param fps: 视频帧率
    :param top_k: 返回匹配的前 k 个结果
    :return: 匹配的时间戳
    """
    D, I = index.search(query_vector, top_k)

    # 根据帧索引计算时间戳
    matched_timestamps = [(timestamps[i], i / fps,i) for i in I[0]]  # 索引对应的时间戳
    print(f"Matched timestamps:{matched_timestamps}")  # 打印匹配的时间戳
    return matched_timestamps