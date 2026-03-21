import faiss
import numpy as np
import os

from src.utils import measure_time


# 索引创建
@measure_time("生成索引耗时：")
def create_clip_index(vectors_list, index_file="cross_video_index.faiss"):
    vectors = np.array(vectors_list).astype("float32")
    vectors = np.array([v/np.linalg.norm(v) if np.linalg.norm(v) != 0 else v for v in vectors])
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    faiss.write_index(index, index_file)
    print(f"Index saved to {index_file}")
    return index

def load_clip_index(index_file="cross_video_index.faiss"):
    if os.path.exists(index_file):
        return faiss.read_index(index_file)
    return None

def search_vector(query_vector, index, timestamps, video_paths, fps, top_k=5):
    D, I = index.search(query_vector, top_k)

    # 计算每个匹配的时间戳
    matched_results = []
    for j, i in enumerate(I[0]):
        # 将帧的索引转换为时间戳
        timestamp = timestamps[i]  # 使用原始帧的时间戳
        video_path = video_paths[i]
        # 计算秒级时间戳
        matched_results.append((timestamp, timestamp, D[0][j], video_path))

    return matched_results

# faiss_index.py

def save_vectors(vectors_list, timestamps, output_file="frame_vectors.npy"):
    folder_path = os.path.dirname(output_file)
    if folder_path and not os.path.exists(folder_path):
        os.makedirs(folder_path)

    # 保存数据
    data = {'vector': np.array(vectors_list).astype("float32"),
            'timestamps': np.array(timestamps).astype("float32")}

    np.save(output_file, data)
    print(f"Vectors and timestamps saved to {output_file}")
    return data

def load_vectors(input_file="frame_vectors.npy"):
    if os.path.exists(input_file):
        data = np.load(input_file, allow_pickle=True).item()
        return data
    else:
        print(f"Error: File {input_file} does not exist.")
        return None