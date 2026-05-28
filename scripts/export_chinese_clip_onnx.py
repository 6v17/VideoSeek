"""Export Chinese CLIP text/image encoders to ONNX (512-d projected features).

The wrappers must return `.pooler_output` from `get_*_features`. Newer
transformers returns a dataclass from those helpers; exporting the object
directly produces (batch, seq, 768) tensors instead of CLIP embeddings.

Example:
    python scripts/export_chinese_clip_onnx.py
    python scripts/export_chinese_clip_onnx.py --sample-image path/to.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from PIL import Image
from transformers import ChineseCLIPConfig, ChineseCLIPModel, ChineseCLIPProcessor

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ONNX_DIR = ROOT / "models" / "chinese-clip" / "vit-base-patch16"
DEFAULT_PYTORCH_DIR = ROOT / "models" / "chinese_clip"
DEFAULT_SAMPLE_IMAGE = DEFAULT_PYTORCH_DIR / "festival.jpg"


class TextEncoder(torch.nn.Module):
    def __init__(self, model: ChineseCLIPModel):
        super().__init__()
        self.model = model

    def forward(self, input_ids, attention_mask):
        outputs = self.model.get_text_features(input_ids=input_ids, attention_mask=attention_mask)
        return outputs.pooler_output


class ImageEncoder(torch.nn.Module):
    def __init__(self, model: ChineseCLIPModel):
        super().__init__()
        self.model = model

    def forward(self, pixel_values):
        outputs = self.model.get_image_features(pixel_values=pixel_values)
        return outputs.pooler_output


def _load_model(processor_dir: Path, weights_dir: Path) -> ChineseCLIPModel:
    config = ChineseCLIPConfig.from_pretrained(str(processor_dir), local_files_only=True)
    model = ChineseCLIPModel.from_pretrained(
        str(weights_dir),
        config=config,
        local_files_only=True,
    )
    model.eval()
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Chinese CLIP ONNX encoders.")
    parser.add_argument("--onnx-dir", type=Path, default=DEFAULT_ONNX_DIR)
    parser.add_argument("--pytorch-dir", type=Path, default=DEFAULT_PYTORCH_DIR)
    parser.add_argument("--sample-image", type=Path, default=DEFAULT_SAMPLE_IMAGE)
    parser.add_argument("--opset", type=int, default=17)
    args = parser.parse_args()

    onnx_dir = args.onnx_dir.resolve()
    pytorch_dir = args.pytorch_dir.resolve()
    onnx_dir.mkdir(parents=True, exist_ok=True)

    if not args.sample_image.is_file():
        raise FileNotFoundError(f"Sample image not found: {args.sample_image}")

    processor = ChineseCLIPProcessor.from_pretrained(str(onnx_dir), local_files_only=True)
    model = _load_model(onnx_dir, pytorch_dir)

    texts = ["节日庆典"]
    text_inputs = processor(text=texts, return_tensors="pt", padding=True)
    image = Image.open(args.sample_image).convert("RGB")
    image_inputs = processor(images=image, return_tensors="pt")

    text_wrapper = TextEncoder(model)
    image_wrapper = ImageEncoder(model)

    text_path = onnx_dir / "chinese_clip_text.onnx"
    image_path = onnx_dir / "chinese_clip_image.onnx"

    torch.onnx.export(
        text_wrapper,
        (text_inputs["input_ids"], text_inputs["attention_mask"]),
        str(text_path),
        input_names=["input_ids", "attention_mask"],
        output_names=["text_features"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "sequence"},
            "attention_mask": {0: "batch", 1: "sequence"},
            "text_features": {0: "batch"},
        },
        opset_version=args.opset,
    )
    print(f"exported text -> {text_path}")

    torch.onnx.export(
        image_wrapper,
        (image_inputs["pixel_values"],),
        str(image_path),
        input_names=["pixel_values"],
        output_names=["image_features"],
        dynamic_axes={
            "pixel_values": {0: "batch"},
            "image_features": {0: "batch"},
        },
        opset_version=args.opset,
    )
    print(f"exported image -> {image_path}")


if __name__ == "__main__":
    main()
