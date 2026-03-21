import clip
import torch
from PIL import Image
import numpy as np

device = "cuda" if torch.cuda.is_available() else "cpu"
model, preprocess = clip.load("ViT-B/32", device=device)

from concurrent.futures import ThreadPoolExecutor

def get_clip_embeddings_batch(frames, batch_size=32, device="cuda"):
    """
    批量处理 CLIP 向量生成，使用多线程加速
    """
    if isinstance(frames, (str, np.ndarray)):
        frames = [frames]

    all_features = []

    # 创建线程池
    with ThreadPoolExecutor() as executor:
        # 分批处理帧
        batch_results = []
        for i in range(0, len(frames), batch_size):
            batch = frames[i:i+batch_size]
            batch_results.append(executor.submit(process_batch, batch, device))

        # 等待所有任务完成
        for future in batch_results:
            all_features.append(future.result())

    return np.vstack(all_features)

def process_batch(batch, device):
    """
    处理单个批次的帧并返回特征
    """
    image_inputs = torch.stack([
        preprocess(Image.open(frame)) if isinstance(frame, str)
        else preprocess(Image.fromarray(frame))
        for frame in batch
    ]).to(device)

    with torch.no_grad():
        features = model.encode_image(image_inputs)
    features = features / features.norm(dim=-1, keepdim=True)
    return features.cpu().numpy()
