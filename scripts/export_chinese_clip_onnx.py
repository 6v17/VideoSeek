"""Export Chinese CLIP text/image encoders to ONNX (projected features).

Wrappers must return projected embeddings from ``get_*_features``. Newer
transformers may return a dataclass; exporting the object directly yields
(batch, seq, hidden) tensors instead of CLIP embeddings.

Examples:
    python scripts/export_chinese_clip_onnx.py --hf-id OFA-Sys/chinese-clip-vit-base-patch16
    python scripts/export_chinese_clip_onnx.py --pack vit-large-patch14
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.vision_model_pack_specs import get_pack_spec  # noqa: E402

DEFAULT_ONNX_DIR = ROOT / "models" / "chinese-clip" / "vit-base-patch16"


def _load_torch_stack():
    try:
        import torch
        from PIL import Image
        from transformers import ChineseCLIPModel, ChineseCLIPProcessor
    except ImportError as exc:
        raise SystemExit(
            "Missing export deps. Install with:\n"
            "  pip install torch transformers pillow onnx\n"
        ) from exc
    return torch, Image, ChineseCLIPModel, ChineseCLIPProcessor


def _projected(features):
    if hasattr(features, "pooler_output"):
        return features.pooler_output
    return features


def _write_manifest(onnx_dir: Path, variant: str, embedding_dimension: int, image_size: int) -> None:
    from src.core.chinese_clip_provider import build_chinese_clip_profile_manifest

    payload = build_chinese_clip_profile_manifest(
        variant,
        embedding_dimension=embedding_dimension,
        image_size=image_size,
    )
    path = onnx_dir / "model_manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote manifest -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Chinese CLIP ONNX encoders.")
    parser.add_argument("--pack", type=str, default="", help="Pack key/variant from vision_model_pack_specs")
    parser.add_argument("--onnx-dir", type=Path, default=None)
    parser.add_argument("--hf-id", type=str, default="")
    parser.add_argument("--variant", type=str, default="")
    parser.add_argument("--embedding-dimension", type=int, default=0)
    parser.add_argument("--image-size", type=int, default=0)
    parser.add_argument("--sample-image", type=Path, default=None)
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    torch, Image, ChineseCLIPModel, ChineseCLIPProcessor = _load_torch_stack()

    hf_id = str(args.hf_id or "").strip()
    variant = str(args.variant or "").strip()
    embedding_dimension = int(args.embedding_dimension or 0)
    image_size = int(args.image_size or 0)
    onnx_dir = args.onnx_dir

    if args.pack:
        spec = get_pack_spec(args.pack)
        if spec["provider"] != "chinese_clip_onnx":
            raise SystemExit(f"--pack {args.pack} is not a Chinese CLIP pack")
        hf_id = hf_id or str(spec["hf_id"])
        variant = variant or str(spec["variant"])
        embedding_dimension = embedding_dimension or int(spec["embedding_dimension"])
        image_size = image_size or int(spec["image_size"])
        if onnx_dir is None:
            onnx_dir = ROOT / "models" / spec["provider_dir"] / variant

    if not hf_id:
        hf_id = "OFA-Sys/chinese-clip-vit-base-patch16"
    if not variant:
        variant = "vit-base-patch16"
    if embedding_dimension <= 0:
        embedding_dimension = 512
    if image_size <= 0:
        image_size = 224
    if onnx_dir is None:
        onnx_dir = DEFAULT_ONNX_DIR
    onnx_dir = onnx_dir.resolve()
    onnx_dir.mkdir(parents=True, exist_ok=True)

    processor = ChineseCLIPProcessor.from_pretrained(
        hf_id, local_files_only=bool(args.local_files_only)
    )
    model = ChineseCLIPModel.from_pretrained(hf_id, local_files_only=bool(args.local_files_only))
    model.eval()
    processor.save_pretrained(str(onnx_dir))
    model.config.to_json_file(str(onnx_dir / "config.json"))
    # Some HF Chinese-CLIP repos only ship vocab.txt (no tokenizer.json). Copy sidecars
    # from the source tree when processor.save_pretrained omits them.
    src_root = Path(hf_id)
    if src_root.is_dir():
        for name in ("vocab.txt", "preprocessor_config.json", "config.json", "tokenizer_config.json"):
            src = src_root / name
            dst = onnx_dir / name
            if src.is_file() and not dst.is_file():
                dst.write_bytes(src.read_bytes())
    for name in ("vocab.txt", "preprocessor_config.json", "config.json"):
        if not (onnx_dir / name).is_file():
            raise RuntimeError(f"Missing required sidecar after save: {onnx_dir / name}")

    class TextEncoder(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.model = inner

        def forward(self, input_ids, attention_mask):
            return _projected(
                self.model.get_text_features(input_ids=input_ids, attention_mask=attention_mask)
            )

    class ImageEncoder(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.model = inner

        def forward(self, pixel_values):
            return _projected(self.model.get_image_features(pixel_values=pixel_values))

    texts = ["节日庆典"]
    text_inputs = processor(text=texts, return_tensors="pt", padding=True)
    if args.sample_image and args.sample_image.is_file():
        image = Image.open(args.sample_image).convert("RGB")
    else:
        image = Image.new("RGB", (image_size, image_size), color=(128, 128, 128))
    image_inputs = processor(images=image, return_tensors="pt")

    text_path = onnx_dir / "chinese_clip_text.onnx"
    image_path = onnx_dir / "chinese_clip_image.onnx"

    torch.onnx.export(
        TextEncoder(model),
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
        ImageEncoder(model),
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
    _write_manifest(onnx_dir, variant, embedding_dimension, image_size)


if __name__ == "__main__":
    main()
