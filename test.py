"""Quick Chinese CLIP ONNX smoke test (image-text similarity).

Requires: numpy, onnxruntime, transformers, pillow

Example:
    python test.py
    python test.py --image models/chinese_clip/festival.jpg
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image
from transformers import ChineseCLIPProcessor

ROOT = Path(__file__).resolve().parent
ONNX_DIR = ROOT / "models" / "chinese-clip" / "vit-base-patch16"
DEFAULT_IMAGE = r"C:\Users\LiuWei\Pictures\Camera Roll\微信图片_20260412114606_174_212.png"

TEXTS = [
    "二次元动漫少女",
    "动漫人物",
    "卡通女孩",
    "女性角色",
    "风景",
]


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return matrix / norms


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--onnx-dir", type=Path, default=ONNX_DIR)
    args = parser.parse_args()

    if not args.image.is_file():
        raise FileNotFoundError(f"Image not found: {args.image}")

    processor = ChineseCLIPProcessor.from_pretrained(str(args.onnx_dir), local_files_only=True)
    text_session = ort.InferenceSession(
        str(args.onnx_dir / "chinese_clip_text.onnx"),
        providers=["CPUExecutionProvider"],
    )
    image_session = ort.InferenceSession(
        str(args.onnx_dir / "chinese_clip_image.onnx"),
        providers=["CPUExecutionProvider"],
    )

    image = Image.open(args.image).convert("RGB")
    image_inputs = processor(images=image, return_tensors="np")
    image_features = image_session.run(None, {"pixel_values": image_inputs["pixel_values"]})[0]

    text_inputs = processor(text=TEXTS, return_tensors="np", padding=True)
    text_features = text_session.run(
        None,
        {
            "input_ids": text_inputs["input_ids"],
            "attention_mask": text_inputs["attention_mask"],
        },
    )[0]

    scores = _normalize(image_features) @ _normalize(text_features).T

    print(f"\nimage: {args.image}")
    print("\n===== similarity =====\n")
    for text, score in zip(TEXTS, scores[0]):
        print(f"{text}: {score:.4f}")


if __name__ == "__main__":
    main()
