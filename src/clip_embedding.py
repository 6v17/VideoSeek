import onnxruntime as ort
import numpy as np
import cv2
import os
import base64

# --- 【关键改动：不再导入原版 clip】 ---
from src.tokenizer import tokenize
from src.extract_frames import extract_frames_with_ffmpeg
from src.faiss_index import save_vectors, create_clip_index
from src.utils import get_resource_path, ensure_folder_exists, measure_time, free_memory

class CLIPOnnxEngine:
    def __init__(self):
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        self.visual_session = ort.InferenceSession(get_resource_path("models/clip_visual.onnx"), providers=providers)
        self.text_session = ort.InferenceSession(get_resource_path("models/clip_text.onnx"), providers=providers)
        self.mean = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32).reshape(1, 1, 3)
        self.std = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32).reshape(1, 1, 3)

    def _preprocess(self, img_bgr):
        """手动图片预处理：增加强制精度转换"""
        img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (224, 224), interpolation=cv2.INTER_CUBIC)

        # 归一化并强制转换为 float32
        img = img.astype(np.float32) / 255.0
        img = (img - self.mean) / self.std

        # HWC -> CHW
        img = img.transpose(2, 0, 1)
        # 【修复点 2】：确保最终返回的是 float32 数组
        return img[np.newaxis, :].astype(np.float32)

        # encode_images 里面如果还有精度问题，也可以在 run 之前加一句

    def imread_chinese(self, path):
        with open(path, 'rb') as f:
            data = f.read()
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        return img
    def encode_images(self, frames):
        # 确定特征维度（只在第一次调用时获取，可以缓存为实例变量）
        if not hasattr(self, '_feature_dim'):
            # 用一张假图跑一次推理获取维度
            dummy = np.zeros((1, 3, 224, 224), dtype=np.float32)  # 根据你的模型输入调整
            dummy_feat = self.visual_session.run(None, {'input': dummy})[0]
            self._feature_dim = dummy_feat.shape[1] if dummy_feat.ndim > 1 else dummy_feat.shape[0]

        embeddings = []
        for f in frames:
            # 读取图像（支持中文路径）
            if isinstance(f, str):
                img = self.imread_chinese(f)  # 自定义函数
            else:
                img = f
            if img is None:
                continue
            blob = self._preprocess(img)
            feat = self.visual_session.run(None, {'input': blob})[0]
            feat = feat.astype(np.float32)
            feat /= (np.linalg.norm(feat, axis=-1, keepdims=True) + 1e-10)
            embeddings.append(feat)

        if not embeddings:
            return np.empty((0, self._feature_dim), dtype=np.float32)

        return np.vstack(embeddings)

    def encode_text(self, text):
        """文字特征提取：同样确保输入类型正确"""
        # tokens 通常是 int32 或 int64，这里用 numpy 转换一下
        tokens = tokenize([text]).astype(np.int32)
        # 运行推理
        feat = self.text_session.run(None, {'input': tokens})[0]
        # 结果也强制转为 float32
        feat = feat.astype(np.float32)
        feat /= (np.linalg.norm(feat, axis=-1, keepdims=True) + 1e-10)
        return feat

engine = CLIPOnnxEngine()

def get_clip_embeddings_batch(frames):
    return engine.encode_images(frames)

def get_text_embedding(text):
    return engine.encode_text(text)


#生成向量
@measure_time("生成向量与索引耗时：")
def generate_vectors_and_index_for_video(video_path, video_name, index_dir, vector_dir):
    frames, timestamps = extract_frames_with_ffmpeg(video_path)
    if not frames: return [], [], None
    vectors = engine.encode_images(frames)
    free_memory()
    safe_video_name = base64.urlsafe_b64encode(video_name.encode()).decode()
    vector_file = os.path.join(vector_dir, f"{safe_video_name}_vectors.npy")
    ensure_folder_exists(vector_file)
    save_vectors(vectors, timestamps, vector_file)
    index_file = os.path.join(index_dir, f"{safe_video_name}_index.faiss")
    ensure_folder_exists(index_file)
    index = create_clip_index(vectors, index_file)
    return vectors, timestamps, index