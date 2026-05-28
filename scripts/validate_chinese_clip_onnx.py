"""Compare Chinese CLIP PyTorch weights against exported ONNX encoders.

Requires (not in default app runtime): torch, transformers, onnxruntime, pillow.

Example:
    python scripts/validate_chinese_clip_onnx.py
    python scripts/validate_chinese_clip_onnx.py --image path/to/test.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ONNX_DIR = ROOT / "models" / "chinese-clip" / "vit-base-patch16"
DEFAULT_PYTORCH_DIR = ROOT / "models" / "chinese_clip"
DEFAULT_IMAGE = DEFAULT_PYTORCH_DIR / "festival.jpg"
TEXT_SAMPLES = ["节日庆典", "城市夜景", "一只猫", "风景"]


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    left = np.asarray(a, dtype=np.float64).reshape(-1)
    right = np.asarray(b, dtype=np.float64).reshape(-1)
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 0:
        return 0.0
    return float(np.dot(left, right) / denom)


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return matrix / norms


def _load_optional_deps():
    try:
        import onnxruntime as ort
        import torch
        from PIL import Image
        from transformers import ChineseCLIPConfig, ChineseCLIPModel, ChineseCLIPProcessor
    except ImportError as exc:
        print(
            "Missing dependency for validation. Install with:\n"
            "  pip install torch transformers onnxruntime pillow",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    return ort, torch, Image, ChineseCLIPConfig, ChineseCLIPModel, ChineseCLIPProcessor


def _resolve_image_path(raw: str | None) -> Path:
    if raw:
        path = Path(raw)
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")
        return path
    if DEFAULT_IMAGE.is_file():
        return DEFAULT_IMAGE
    raise FileNotFoundError(
        f"No --image provided and default sample missing: {DEFAULT_IMAGE}"
    )


def _assert_onnx_shapes(text_arr: np.ndarray, image_arr: np.ndarray) -> None:
    if text_arr.ndim != 2 or text_arr.shape[1] != 512:
        raise RuntimeError(
            f"Text ONNX output has wrong shape {text_arr.shape}; expected (batch, 512). "
            "Re-export with: python scripts/export_chinese_clip_onnx.py"
        )
    if image_arr.ndim != 2 or image_arr.shape[1] != 512:
        raise RuntimeError(
            f"Image ONNX output has wrong shape {image_arr.shape}; expected (batch, 512). "
            "Re-export with: python scripts/export_chinese_clip_onnx.py"
        )


def _pytorch_features(model, text_inputs, image_inputs, torch):
    text_pt = {
        key: torch.from_numpy(text_inputs[key])
        for key in ("input_ids", "attention_mask")
    }
    image_pt = {"pixel_values": torch.from_numpy(image_inputs["pixel_values"])}
    with torch.no_grad():
        pt_text = model.get_text_features(**text_pt).pooler_output.cpu().numpy().astype(np.float32)
        pt_image = model.get_image_features(**image_pt).pooler_output.cpu().numpy().astype(np.float32)
    return pt_text, pt_image


def _run_onnx_text(session, processor, texts, ort):
    inputs = processor(text=list(texts), return_tensors="np", padding=True)
    outputs = session.run(
        None,
        {
            "input_ids": inputs["input_ids"],
            "attention_mask": inputs["attention_mask"],
        },
    )
    if len(outputs) != 1:
        names = [item.name for item in session.get_outputs()]
        raise RuntimeError(f"Expected 1 text output, got {len(outputs)}: {names}")
    return np.asarray(outputs[0], dtype=np.float32)


def _run_onnx_image(session, processor, image, ort, Image):
    inputs = processor(images=image, return_tensors="np")
    outputs = session.run(None, {"pixel_values": inputs["pixel_values"]})
    if len(outputs) != 1:
        names = [item.name for item in session.get_outputs()]
        raise RuntimeError(f"Expected 1 image output, got {len(outputs)}: {names}")
    return np.asarray(outputs[0], dtype=np.float32)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Chinese CLIP ONNX export against PyTorch.")
    parser.add_argument("--onnx-dir", type=Path, default=DEFAULT_ONNX_DIR)
    parser.add_argument("--pytorch-dir", type=Path, default=DEFAULT_PYTORCH_DIR)
    parser.add_argument("--image", type=str, default=None, help="Test image path (default: models/chinese_clip/festival.jpg)")
    parser.add_argument("--text-cos-threshold", type=float, default=0.999)
    parser.add_argument("--max-abs-threshold", type=float, default=1e-3)
    args = parser.parse_args()

    ort, torch, Image, ChineseCLIPConfig, ChineseCLIPModel, ChineseCLIPProcessor = _load_optional_deps()

    onnx_dir = args.onnx_dir.resolve()
    pytorch_dir = args.pytorch_dir.resolve()
    image_path = _resolve_image_path(args.image)

    text_onnx = onnx_dir / "chinese_clip_text.onnx"
    image_onnx = onnx_dir / "chinese_clip_image.onnx"
    for path in (text_onnx, image_onnx, pytorch_dir / "pytorch_model.bin"):
        if not path.is_file():
            print(f"Missing required file: {path}", file=sys.stderr)
            return 2

    processor = ChineseCLIPProcessor.from_pretrained(str(onnx_dir), local_files_only=True)
    config = ChineseCLIPConfig.from_pretrained(str(onnx_dir), local_files_only=True)
    model = ChineseCLIPModel.from_pretrained(
        str(pytorch_dir),
        config=config,
        local_files_only=True,
    )
    model.eval()

    text_session = ort.InferenceSession(str(text_onnx), providers=["CPUExecutionProvider"])
    image_session = ort.InferenceSession(str(image_onnx), providers=["CPUExecutionProvider"])

    image = Image.open(image_path).convert("RGB")
    text_inputs = processor(text=list(TEXT_SAMPLES), return_tensors="np", padding=True)
    image_inputs = processor(images=image, return_tensors="np")

    with torch.no_grad():
        pt_text, pt_image = _pytorch_features(model, text_inputs, image_inputs, torch)

    onnx_text = _run_onnx_text(text_session, processor, TEXT_SAMPLES, ort)
    onnx_image = _run_onnx_image(image_session, processor, image, ort, Image)
    try:
        _assert_onnx_shapes(onnx_text, onnx_image)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    text_cos = [_cosine(pt_text[i], onnx_text[i]) for i in range(len(TEXT_SAMPLES))]
    image_cos = _cosine(pt_image[0], onnx_image[0])
    text_max_abs = float(np.max(np.abs(pt_text - onnx_text)))
    image_max_abs = float(np.max(np.abs(pt_image - onnx_image)))

    pt_text_n = _normalize_rows(pt_text)
    pt_image_n = _normalize_rows(pt_image)
    onnx_text_n = _normalize_rows(onnx_text)
    onnx_image_n = _normalize_rows(onnx_image)
    pt_scores = pt_image_n @ pt_text_n.T
    onnx_scores = onnx_image_n @ onnx_text_n.T

    print("=== Chinese CLIP ONNX validation ===")
    print(f"onnx_dir     : {onnx_dir}")
    print(f"pytorch_dir  : {pytorch_dir}")
    print(f"image        : {image_path}")
    print()
    print(f"text  cosine (per row): min={min(text_cos):.6f}  max={max(text_cos):.6f}")
    print(f"text  max abs diff     : {text_max_abs:.6e}")
    print(f"image cosine           : {image_cos:.6f}")
    print(f"image max abs diff     : {image_max_abs:.6e}")
    print()
    print("=== semantic sanity (image vs text, ONNX) ===")
    for label, score in zip(TEXT_SAMPLES, onnx_scores[0]):
        print(f"  {score:.4f}  {label}")
    print()
    print("=== PyTorch scores (reference) ===")
    for label, score in zip(TEXT_SAMPLES, pt_scores[0]):
        print(f"  {score:.4f}  {label}")

    ok = (
        min(text_cos) >= args.text_cos_threshold
        and image_cos >= args.text_cos_threshold
        and text_max_abs <= args.max_abs_threshold
        and image_max_abs <= args.max_abs_threshold
    )
    if ok:
        print("\nPASS: ONNX export matches PyTorch within thresholds.")
        return 0

    print("\nFAIL: ONNX drift exceeds thresholds.", file=sys.stderr)
    print(
        f"  require cos>={args.text_cos_threshold}, max_abs<={args.max_abs_threshold}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
