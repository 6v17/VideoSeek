import cv2
import torch
import clip
from PIL import Image
import numpy as np
import os
from src.extract_frames import extract_frames_with_ffmpeg
from src.faiss_index import save_vectors, create_clip_index
from src.utils import free_memory, ensure_folder_exists, measure_time, get_resource_path

# 加载模型
device = "cuda" if torch.cuda.is_available() else "cpu"
model_path = get_resource_path(os.path.join("models", "ViT-B-32.pt"))
model, preprocess = clip.load(model_path, device=device)


def get_clip_embeddings_batch(frames, batch_size=32):
    all_features = []
    # 分批次处理
    for i in range(0, len(frames), batch_size):
        batch = frames[i: i + batch_size]

        inputs = []
        for f in batch:
            # --- 【核心修复逻辑】 ---
            if isinstance(f, str):
                # 如果 f 是文件路径（图片搜索时）
                img = Image.open(f).convert("RGB")
            elif isinstance(f, np.ndarray):
                # 如果 f 是 OpenCV 图像数组（视频抽帧时）
                img = Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
            else:
                continue

            inputs.append(preprocess(img))

        if not inputs:
            continue

        image_input = torch.stack(inputs).to(device)

        with torch.no_grad():
            features = model.encode_image(image_input)
            features /= features.norm(dim=-1, keepdim=True)
            all_features.append(features.cpu().numpy())

    return np.vstack(all_features)


def get_text_embedding(text):
    # 【优化】给文字加个模板，CLIP 对这种格式感应更强
    prompt = f"a video of {text}"
    text_input = clip.tokenize([prompt]).to(device)
    with torch.no_grad():
        features = model.encode_text(text_input)
    # 必须归一化
    features /= features.norm(dim=-1, keepdim=True)
    return features.cpu().numpy()


@measure_time("生成向量耗时：")
def generate_vectors_and_index_for_video(video_path, video_name, index_dir, vector_dir):
    """供 update_video.py 调用：处理单个视频"""
    frames, timestamps = extract_frames_with_ffmpeg(video_path)
    if not frames: return [], [], None

    vectors = get_clip_embeddings_batch(frames)
    free_memory()

    # 安全的文件名处理
    import base64
    safe_name = base64.urlsafe_b64encode(video_name.encode()).decode()

    vector_file = os.path.join(vector_dir, f"{safe_name}_vectors.npy")
    ensure_folder_exists(vector_file)
    save_vectors(vectors, timestamps, vector_file)

    index_file = os.path.join(index_dir, f"{safe_name}_index.faiss")
    ensure_folder_exists(index_file)
    index = create_clip_index(vectors, index_file)

    return vectors, timestamps, index