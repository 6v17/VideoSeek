import os

import cv2
import numpy as np
import onnxruntime as ort

from src.core.extract_frames import extract_frames_with_ffmpeg
from src.core.faiss_index import create_clip_index, save_vectors
from src.core.tokenizer import tokenize
from src.utils import ensure_folder_exists, ensure_model_files, free_memory, measure_time


class CLIPOnnxEngine:
    def __init__(self):
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        model_paths = ensure_model_files(["clip_visual.onnx", "clip_text.onnx"])
        self.visual_session = ort.InferenceSession(
            model_paths["clip_visual.onnx"],
            providers=providers,
        )
        self.text_session = ort.InferenceSession(
            model_paths["clip_text.onnx"],
            providers=providers,
        )
        self.mean = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32).reshape(1, 1, 3)
        self.std = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32).reshape(1, 1, 3)
        self._feature_dim = None

    def _preprocess(self, img_bgr):
        img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (224, 224), interpolation=cv2.INTER_CUBIC)
        img = img.astype(np.float32) / 255.0
        img = (img - self.mean) / self.std
        img = img.transpose(2, 0, 1)
        return img[np.newaxis, :].astype(np.float32)

    def imread_chinese(self, path):
        with open(path, "rb") as handle:
            data = handle.read()
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

    def encode_images(self, frames):
        if self._feature_dim is None:
            dummy = np.zeros((1, 3, 224, 224), dtype=np.float32)
            dummy_feat = self.visual_session.run(None, {"input": dummy})[0]
            self._feature_dim = dummy_feat.shape[1] if dummy_feat.ndim > 1 else dummy_feat.shape[0]

        embeddings = []
        for frame in frames:
            image = self.imread_chinese(frame) if isinstance(frame, str) else frame
            if image is None:
                continue
            blob = self._preprocess(image)
            feat = self.visual_session.run(None, {"input": blob})[0].astype(np.float32)
            feat /= (np.linalg.norm(feat, axis=-1, keepdims=True) + 1e-10)
            embeddings.append(feat)

        if not embeddings:
            return np.empty((0, self._feature_dim), dtype=np.float32)
        free_memory()
        return np.vstack(embeddings)

    def encode_text(self, text):
        tokens = tokenize([text]).astype(np.int32)
        feat = self.text_session.run(None, {"input": tokens})[0].astype(np.float32)
        feat /= (np.linalg.norm(feat, axis=-1, keepdims=True) + 1e-10)
        return feat


engine = None


def get_engine():
    global engine
    if engine is None:
        engine = CLIPOnnxEngine()
    return engine


def get_clip_embeddings_batch(frames):
    return get_engine().encode_images(frames)


def get_text_embedding(text):
    return get_engine().encode_text(text)


@measure_time("Video indexing time:")
def generate_vectors_and_index_for_video(video_path, video_id, index_dir, vector_dir):
    frames, timestamps = extract_frames_with_ffmpeg(video_path)
    if not frames:
        return [], [], None

    vectors = get_engine().encode_images(frames)
    free_memory()

    vector_file = os.path.normpath(os.path.join(vector_dir, f"{video_id}_vectors.npy"))
    index_file = os.path.normpath(os.path.join(index_dir, f"{video_id}_index.faiss"))

    ensure_folder_exists(vector_file)
    save_vectors(vectors, timestamps, vector_file)

    ensure_folder_exists(index_file)
    index = create_clip_index(vectors, index_file)
    return vectors, timestamps, index
