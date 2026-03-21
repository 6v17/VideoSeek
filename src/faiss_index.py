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


def search_vector(query_vector, index, timestamps, video_paths, top_k=5):
    """
    基于查询向量从索引中搜索相似项
    :param query_vector: 查询向量
    :param index: Faiss索引对象
    :param timestamps: 时间戳列表
    :param video_paths: 视频路径列表
    :param top_k: 返回的最相似结果数量
    :return: 匹配的结果列表
    """
    D, I = index.search(query_vector, top_k)  # D: 距离，I: 索引

    # 计算匹配的时间戳
    matched_results = []
    for j, i in enumerate(I[0]):
        timestamp = timestamps[i]  # 获取原始时间戳
        video_path = video_paths[i]
        matched_results.append((timestamp, timestamp, D[0][j], video_path))  # (timestamp, sec, similarity, video_path)


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