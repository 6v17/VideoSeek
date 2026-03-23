import faiss
import numpy as np
import os

from src.utils import measure_time


# 索引创建
@measure_time("生成索引耗时：")
def create_clip_index(vectors_list, index_file):
    vectors = np.array(vectors_list).astype("float32")

    # 归一化
    vectors = np.array([v / np.linalg.norm(v) if np.linalg.norm(v) != 0 else v for v in vectors])

    # 创建Faiss索引
    index = faiss.IndexFlatIP(vectors.shape[1])  # 使用内积（IP）索引
    index.add(vectors)  # 向索引添加向量
    faiss.write_index(index, index_file)
    print(f"索引保存路径 {index_file}")
    return index


def load_clip_index(index_file):
    """
    加载Faiss索引文件
    :param index_file: 索引文件路径
    :return: Faiss索引对象
    """
    if os.path.exists(index_file):
        return faiss.read_index(index_file)
    return None


def search_vector(query_vector, index, timestamps, video_paths, top_k=10):
    # 增加防御：如果库里总帧数还没 top_k 多，就搜全部
    actual_k = min(top_k, index.ntotal)
    if actual_k <= 0: return []

    D, I = index.search(query_vector, actual_k)

    matched_results = []
    for j, i in enumerate(I[0]):
        if i == -1 or i >= len(video_paths):  # 关键修复：过滤无效索引
            continue
        timestamp = timestamps[i]
        video_path = video_paths[i]
        matched_results.append((timestamp, timestamp, D[0][j], video_path))
    return matched_results

# 保存向量
def save_vectors(vectors_list, timestamps, output_file):
    """
    保存向量和时间戳到文件
    :param vectors_list: 向量列表
    :param timestamps: 时间戳列表
    :param output_file: 输出文件路径
    :return: 保存的数据
    """
    folder_path = os.path.dirname(output_file)
    if folder_path and not os.path.exists(folder_path):
        os.makedirs(folder_path)

    # 保存向量数据
    data = {'vector': np.array(vectors_list).astype("float32"),
            'timestamps': np.array(timestamps).astype("float32")}

    np.save(output_file, data)
    print(f"向量保存路径： {output_file}")
    return data


# 加载向量
def load_vectors(input_file):
    """
    加载向量和时间戳文件
    :param input_file: 输入文件路径
    :return: 加载的数据
    """
    if os.path.exists(input_file):
        data = np.load(input_file, allow_pickle=True).item()
        return data
    else:
        print(f"文件不存在: {input_file} ")
        return None