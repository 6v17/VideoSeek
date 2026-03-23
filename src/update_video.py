# --- src/update_video.py ---
import gc
import os
import numpy as np
from src.clip_embedding import generate_vectors_and_index_for_video
from src.faiss_index import create_clip_index, save_vectors, load_vectors
from src.utils import save_meta, load_meta, get_video_hash, ensure_folder_exists
from src.config import load_config


def get_video_id(abs_path):
    """获取视频内容的唯一哈希（取前10MB）"""
    return get_video_hash(abs_path)


def load_video_vectors_by_id(vid, config):
    """通过视频ID加载向量"""
    vector_file = os.path.join(config["vector_dir"], f"{vid}_vectors.npy")
    data = load_vectors(vector_file)
    if data is not None and isinstance(data, dict):
        return data.get('vector'), data.get('timestamps')
    return None, None


def process_single_video_in_lib(abs_path, rel_path, lib_files, config):
    """处理单个视频：Hash一致则加载，不一致则生成"""
    try:
        vid = get_video_id(abs_path)
        video_mod_time = os.path.getmtime(abs_path)

        # 如果 meta 记录的哈希和修改时间都没变
        saved = lib_files.get(rel_path, {})
        if saved.get("vid") == vid and saved.get("mod_time") == video_mod_time:
            v, t = load_video_vectors_by_id(vid, config)
            if v is not None:
                return v, t

        # 否则重新生成，注意这里传的是 vid (Hash)
        print(f"[索引中] {os.path.basename(abs_path)}")
        vectors, timestamps, _ = generate_vectors_and_index_for_video(
            abs_path, vid, config["index_dir"], config["vector_dir"]
        )

        # 更新 meta 记录
        lib_files[rel_path] = {"vid": vid, "mod_time": video_mod_time}
        return vectors, timestamps
    except Exception as e:
        print(f"处理视频错误 {abs_path}: {e}")
        return None, None


# src/update_video.py 核心修改部分

def update_videos_flow(target_lib=None, progress_callback=None):
    """
    progress_callback: 格式为 func(int_percent, str_text)
    """
    #清理
    garbage_collect_indices()
    config = load_config()
    meta = load_meta(config["meta_file"])

    VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm')
    all_v, all_t, all_p = [], [], []
    # --- A. 失效数据清理阶段 ---
    if progress_callback: progress_callback(5, "正在清理失效索引...")

    for root_path, lib_data in list(meta["libraries"].items()):
        # 如果指定了库，只清理该库；否则清理全量
        if target_lib and os.path.normpath(root_path) != os.path.normpath(target_lib):
            continue

        lib_files = lib_data.get("files", {})
        removed_count = 0

        # 遍历已记录的文件，检查磁盘上是否还存在
        for rel_p in list(lib_files.keys()):
            abs_p = os.path.join(root_path, rel_p)
            if not os.path.exists(abs_p):
                vid = lib_files[rel_p].get("vid")
                delete_physical_video_data(vid, config)  # 调用工具
                del lib_files[rel_p]

    # 1. 扫描与提取
    libs_to_scan = meta["libraries"].items()
    lib_count = len(libs_to_scan)

    for i, (root_path, lib_data) in enumerate(libs_to_scan):
        # 进度反馈
        if progress_callback:
            progress_callback(int((i / lib_count) * 100), f"正在扫描库: {os.path.basename(root_path)}")

        if target_lib and os.path.normpath(root_path) != os.path.normpath(target_lib):
            # 不扫描，直接加载缓存
            lib_files = lib_data.get("files", {})
            for rel_p, info in lib_files.items():
                v, t = load_video_vectors_by_id(info["vid"], config)
                if v is not None:
                    all_v.append(v)
                    all_t.extend(t)
                    all_p.extend([os.path.join(root_path, rel_p)] * len(t))
            continue

        if not os.path.exists(root_path): continue

        lib_files = lib_data.get("files", {})
        # 获取该目录下所有视频文件
        valid_files = []
        for r, _, fs in os.walk(root_path):
            for f in fs:
                if f.lower().endswith(VIDEO_EXTS):
                    valid_files.append(os.path.join(r, f))

        for j, abs_p in enumerate(valid_files):
            rel_p = os.path.relpath(abs_p, root_path)
            if progress_callback:
                progress_callback(int((j / len(valid_files)) * 100), f"处理中: {os.path.basename(abs_p)}")

            v, t = process_single_video_in_lib(abs_p, rel_p, lib_files, config)
            if v is not None:
                all_v.append(v)
                all_t.extend(t)
                all_p.extend([abs_p] * len(t))

        lib_data["files"] = lib_files

    save_meta(meta, config["meta_file"])
    if not any(len(lib.get("files", {})) > 0 for lib in meta["libraries"].values()):
        for f in [config["cross_index_file"], config["cross_vector_file"]]:
            if os.path.exists(f): os.remove(f)
        return None, None, None, None  # 返回 None 触发 UI 失败/空逻辑

    if not all_v:
        print("所有库均无有效视频。")
        # 清理全局索引
        if os.path.exists(config["cross_index_file"]): os.remove(config["cross_index_file"])
        return None, None, None, None

    # 2. 合并索引
    if progress_callback: progress_callback(95, "正在构建全局索引...")
    v_stack = np.vstack(all_v).astype('float32')
    t_array = np.array(all_t).astype('float32')

    merge_and_save_all_vectors(v_stack, t_array, all_p, config)
    gc.collect()
    from src.faiss_index import load_clip_index
    return v_stack, t_array, np.array(all_p), load_clip_index(config["cross_index_file"])


def merge_and_save_all_vectors(all_v, all_t, all_p, config):
    """保存全局向量数据并构建全局 FAISS 索引"""
    # 确保 global 文件夹存在
    ensure_folder_exists(config["cross_index_file"])
    ensure_folder_exists(config["cross_vector_file"])

    # 构建 FAISS 索引
    create_clip_index(all_v, config["cross_index_file"])

    # 保存向量和对应的视频路径映射（注意：这里的 all_p 和 all_t 是一一对应的）
    data = {
        'vector': all_v,
        'timestamps': all_t,
        'paths': all_p
    }
    np.save(config["cross_vector_file"], data)


def delete_physical_video_data(vid, config):
    """根据 VID 物理删除磁盘上的向量和索引文件"""
    if not vid: return

    # 路径拼接
    v_file = os.path.join(config["vector_dir"], f"{vid}_vectors.npy")
    idx_file = os.path.join(config["index_dir"], f"{vid}_index.faiss")

    try:
        if os.path.exists(v_file):
            os.remove(v_file)
            print(f"[清理] 已删除向量文件: {vid}")
        if os.path.exists(idx_file):
            os.remove(idx_file)
            print(f"[清理] 已删除索引文件: {vid}")
    except Exception as e:
        print(f"物理删除失败 {vid}: {e}")


def garbage_collect_indices():
    """清理 data 文件夹中所有未在 meta.json 中记录的孤儿文件"""
    config = load_config()
    meta = load_meta(config["meta_file"])

    # 获取 meta 中所有合法的 VID
    valid_vids = set()
    for lib in meta["libraries"].values():
        for info in lib.get("files", {}).values():
            if info.get("vid"):
                valid_vids.add(info["vid"])

    # 扫描物理文件夹
    for folder in [config["vector_dir"], config["index_dir"]]:
        if not os.path.exists(folder): continue
        for filename in os.listdir(folder):
            # 假设文件名格式是 {vid}_vectors.npy 或 {vid}_index.faiss
            vid = filename.split('_')[0]
            if vid not in valid_vids and len(vid) > 10:  # 简单校验长度
                try:
                    os.remove(os.path.join(folder, filename))
                    print(f"GC: 删除了孤儿文件 {filename}")
                except:
                    pass