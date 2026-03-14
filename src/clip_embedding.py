import clip
import torch
from PIL import Image
import os

# 自动选择运行设备
device = "cuda" if torch.cuda.is_available() else "cpu"

# 加载 CLIP 模型
model, preprocess = clip.load("ViT-B/32", device=device)

def get_clip_embedding(image_path):  # 生成向量
    image = Image.open(image_path)
    image_input = preprocess(image).unsqueeze(0).to(device)

    with torch.no_grad():
        image_features = model.encode_image(image_input)

    image_features = image_features / image_features.norm(dim=-1, keepdim=True)

    return image_features.cpu().numpy()

import numpy as np

def save_vectors(vectors_list, timestamps, output_file="frame_vectors.npy"):
    """
    保存 CLIP 向量和对应的时间戳。
    :param vectors_list: CLIP 向量列表
    :param timestamps: 时间戳列表
    :param output_file: 输出文件路径
    """
    data = {'vector': np.array(vectors_list).astype("float32"),
            'timestamps': np.array(timestamps).astype("float32")}
    np.save(output_file, data)
    print(f"Vectors and timestamps saved to {output_file}")
    return  data

# 加载已保存的向量
def load_vectors(input_file="frame_vectors.npy"):
    if os.path.exists(input_file):
        data = np.load(input_file, allow_pickle=True).item()  # 加载字典并获取数据
        print(f"Loaded vector from {input_file}")
        return data  # 返回向量和时间戳
    else:
        print(f"{input_file} does not exist!")
        return None