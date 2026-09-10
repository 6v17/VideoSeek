"""Export SigLIP / SigLIP2 vision+text towers to ONNX for VideoSeek ``siglip2_onnx``.

Produces ``vision_model.onnx`` / ``text_model.onnx`` plus tokenizer sidecars.

Examples:
    python scripts/export_siglip2_onnx.py --pack so400m-patch14-224
    python scripts/export_siglip2_onnx.py --hf-id google/siglip2-base-patch16-224 \\
        --variant base-patch16-224 --embedding-dimension 768
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

DEFAULT_ONNX_DIR = ROOT / "models" / "siglip2" / "base-patch16-224"


def _load_torch_stack():
    try:
        import torch
        from PIL import Image
        from transformers import AutoModel, AutoProcessor
    except ImportError as exc:
        raise SystemExit(
            "Missing export deps. Install with:\n"
            "  pip install torch transformers pillow onnx\n"
        ) from exc
    return torch, Image, AutoModel, AutoProcessor


def _projected(features):
    if hasattr(features, "pooler_output"):
        return features.pooler_output
    return features


def _write_manifest(onnx_dir: Path, variant: str, embedding_dimension: int, image_size: int) -> None:
    from src.core.siglip_provider import build_siglip_profile_manifest

    payload = build_siglip_profile_manifest(
        variant,
        embedding_dimension=embedding_dimension,
        image_size=image_size,
    )
    path = onnx_dir / "model_manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote manifest -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export SigLIP2 ONNX encoders for VideoSeek.")
    parser.add_argument("--pack", type=str, default="", help="Pack key/variant from vision_model_pack_specs")
    parser.add_argument("--onnx-dir", type=Path, default=None)
    parser.add_argument("--hf-id", type=str, default="")
    parser.add_argument("--variant", type=str, default="")
    parser.add_argument("--embedding-dimension", type=int, default=0)
    parser.add_argument("--image-size", type=int, default=0)
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    torch, Image, AutoModel, AutoProcessor = _load_torch_stack()

    hf_id = str(args.hf_id or "").strip()
    variant = str(args.variant or "").strip()
    embedding_dimension = int(args.embedding_dimension or 0)
    image_size = int(args.image_size or 0)
    onnx_dir = args.onnx_dir

    if args.pack:
        spec = get_pack_spec(args.pack)
        if spec["provider"] != "siglip2_onnx":
            raise SystemExit(f"--pack {args.pack} is not a SigLIP2 pack")
        hf_id = hf_id or str(spec["hf_id"])
        variant = variant or str(spec["variant"])
        embedding_dimension = embedding_dimension or int(spec["embedding_dimension"])
        image_size = image_size or int(spec["image_size"])
        if onnx_dir is None:
            onnx_dir = ROOT / "models" / spec["provider_dir"] / variant

    if not hf_id:
        hf_id = "google/siglip2-base-patch16-224"
    if not variant:
        variant = "base-patch16-224"
    if embedding_dimension <= 0:
        embedding_dimension = 768
    if image_size <= 0:
        image_size = 224
    if onnx_dir is None:
        onnx_dir = DEFAULT_ONNX_DIR
    onnx_dir = onnx_dir.resolve()
    onnx_dir.mkdir(parents=True, exist_ok=True)

    processor = AutoProcessor.from_pretrained(hf_id, local_files_only=bool(args.local_files_only))
    model = AutoModel.from_pretrained(hf_id, local_files_only=bool(args.local_files_only))
    model.eval()
    processor.save_pretrained(str(onnx_dir))
    for name in ("tokenizer.json", "tokenizer_config.json"):
        if not (onnx_dir / name).is_file():
            raise RuntimeError(f"Missing required tokenizer sidecar: {onnx_dir / name}")

    class VisionEncoder(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.model = inner

        def forward(self, pixel_values):
            return _projected(self.model.get_image_features(pixel_values=pixel_values))

    class TextEncoder(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.model = inner

        def forward(self, input_ids, attention_mask):
            return _projected(
                self.model.get_text_features(input_ids=input_ids, attention_mask=attention_mask)
            )

    image = Image.new("RGB", (image_size, image_size), color=(128, 128, 128))
    image_inputs = processor(images=image, return_tensors="pt")
    text_inputs = processor(
        text=["a photo"],
        return_tensors="pt",
        padding="max_length",
        max_length=64,
        truncation=True,
    )

    vision_path = onnx_dir / "vision_model.onnx"
    text_path = onnx_dir / "text_model.onnx"

    torch.onnx.export(
        VisionEncoder(model),
        (image_inputs["pixel_values"],),
        str(vision_path),
        input_names=["pixel_values"],
        output_names=["image_features"],
        dynamic_axes={"pixel_values": {0: "batch"}, "image_features": {0: "batch"}},
        opset_version=args.opset,
    )
    print(f"exported vision -> {vision_path}")

    class TextEncoderIdsOnly(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.model = inner

        def forward(self, input_ids):
            return _projected(self.model.get_text_features(input_ids=input_ids))

    if "attention_mask" in text_inputs:
        text_args = (text_inputs["input_ids"], text_inputs["attention_mask"])
        try:
            torch.onnx.export(
                TextEncoder(model),
                text_args,
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
        except Exception:
            torch.onnx.export(
                TextEncoderIdsOnly(model),
                (text_inputs["input_ids"],),
                str(text_path),
                input_names=["input_ids"],
                output_names=["text_features"],
                dynamic_axes={
                    "input_ids": {0: "batch", 1: "sequence"},
                    "text_features": {0: "batch"},
                },
                opset_version=args.opset,
            )
    else:
        torch.onnx.export(
            TextEncoderIdsOnly(model),
            (text_inputs["input_ids"],),
            str(text_path),
            input_names=["input_ids"],
            output_names=["text_features"],
            dynamic_axes={"input_ids": {0: "batch", 1: "sequence"}, "text_features": {0: "batch"}},
            opset_version=args.opset,
        )
    print(f"exported text -> {text_path}")
    _write_manifest(onnx_dir, variant, embedding_dimension, image_size)


if __name__ == "__main__":
    main()
