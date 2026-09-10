"""Export OpenAI CLIP visual/text encoders to ONNX for VideoSeek ``clip_onnx``.

I/O matches ``CLIPOnnxEngine``:
  - visual / text input name: ``input``
  - text tokens: OpenAI CLIP BPE (``bpe_simple_vocab_16e6.txt.gz``), length 77

Examples:
    python scripts/export_openai_clip_onnx.py --pack vit-large-patch14
    python scripts/export_openai_clip_onnx.py --hf-id openai/clip-vit-base-patch32 \\
        --variant vit-base-patch32 --embedding-dimension 512
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.vision_model_pack_specs import get_pack_spec  # noqa: E402

DEFAULT_BPE_URL = "https://github.com/openai/CLIP/raw/main/clip/bpe_simple_vocab_16e6.txt.gz"
DEFAULT_ONNX_DIR = ROOT / "models" / "openai-clip" / "vit-base-patch32"


def _load_torch_stack():
    try:
        import torch
        from PIL import Image
        from transformers import CLIPModel, CLIPProcessor
    except ImportError as exc:
        raise SystemExit(
            "Missing export deps. Install with:\n"
            "  pip install torch transformers pillow onnx\n"
        ) from exc
    return torch, Image, CLIPModel, CLIPProcessor


def _projected(features):
    if hasattr(features, "pooler_output"):
        return features.pooler_output
    return features


def _ensure_bpe(onnx_dir: Path, bpe_url: str, bpe_source: Path | None) -> Path:
    target = onnx_dir / "bpe_simple_vocab_16e6.txt.gz"
    if target.is_file():
        return target
    if bpe_source and bpe_source.is_file():
        target.write_bytes(bpe_source.read_bytes())
        return target
    print(f"downloading BPE vocab -> {target}")
    urllib.request.urlretrieve(bpe_url, target)
    return target


def _write_manifest(onnx_dir: Path, variant: str, embedding_dimension: int, image_size: int) -> None:
    from src.services.model_package_service import build_openai_clip_profile_manifest

    payload = build_openai_clip_profile_manifest(
        variant,
        embedding_dimension=embedding_dimension,
        image_size=image_size,
    )
    path = onnx_dir / "model_manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote manifest -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export OpenAI CLIP ONNX encoders for VideoSeek.")
    parser.add_argument("--pack", type=str, default="", help="Pack key/variant from vision_model_pack_specs")
    parser.add_argument("--onnx-dir", type=Path, default=None)
    parser.add_argument("--hf-id", type=str, default="")
    parser.add_argument("--variant", type=str, default="")
    parser.add_argument("--embedding-dimension", type=int, default=0)
    parser.add_argument("--image-size", type=int, default=0)
    parser.add_argument("--bpe-url", type=str, default=DEFAULT_BPE_URL)
    parser.add_argument("--bpe-source", type=Path, default=None, help="Local BPE file to copy")
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    torch, Image, CLIPModel, CLIPProcessor = _load_torch_stack()

    hf_id = str(args.hf_id or "").strip()
    variant = str(args.variant or "").strip()
    embedding_dimension = int(args.embedding_dimension or 0)
    image_size = int(args.image_size or 0)
    bpe_url = str(args.bpe_url or DEFAULT_BPE_URL).strip() or DEFAULT_BPE_URL
    onnx_dir = args.onnx_dir

    if args.pack:
        spec = get_pack_spec(args.pack)
        if spec["provider"] != "clip_onnx":
            raise SystemExit(f"--pack {args.pack} is not an OpenAI CLIP pack")
        hf_id = hf_id or str(spec["hf_id"])
        variant = variant or str(spec["variant"])
        embedding_dimension = embedding_dimension or int(spec["embedding_dimension"])
        image_size = image_size or int(spec["image_size"])
        bpe_url = str(spec.get("bpe_url") or bpe_url)
        if onnx_dir is None:
            onnx_dir = ROOT / "models" / spec["provider_dir"] / variant

    if not hf_id:
        hf_id = "openai/clip-vit-base-patch32"
    if not variant:
        variant = "vit-base-patch32"
    if embedding_dimension <= 0:
        embedding_dimension = 512
    if image_size <= 0:
        image_size = 224
    if onnx_dir is None:
        onnx_dir = DEFAULT_ONNX_DIR
    onnx_dir = onnx_dir.resolve()
    onnx_dir.mkdir(parents=True, exist_ok=True)

    processor = CLIPProcessor.from_pretrained(hf_id, local_files_only=bool(args.local_files_only))
    model = CLIPModel.from_pretrained(hf_id, local_files_only=bool(args.local_files_only))
    model.eval()
    _ensure_bpe(onnx_dir, bpe_url, args.bpe_source)

    class VisualEncoder(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.model = inner

        def forward(self, pixel_values):
            return _projected(self.model.get_image_features(pixel_values=pixel_values))

    class TextEncoder(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.model = inner

        def forward(self, input_ids):
            return _projected(self.model.get_text_features(input_ids=input_ids))

    image = Image.new("RGB", (image_size, image_size), color=(128, 128, 128))
    image_inputs = processor(images=image, return_tensors="pt")
    text_inputs = processor(text=["a photo"], return_tensors="pt", padding="max_length", max_length=77)

    visual_path = onnx_dir / "clip_visual.onnx"
    text_path = onnx_dir / "clip_text.onnx"

    torch.onnx.export(
        VisualEncoder(model),
        (image_inputs["pixel_values"],),
        str(visual_path),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        opset_version=args.opset,
    )
    print(f"exported visual -> {visual_path}")

    # VideoSeek feeds int32 tokens named ``input``.
    token_ids = text_inputs["input_ids"].to(dtype=torch.int32)
    torch.onnx.export(
        TextEncoder(model),
        (token_ids,),
        str(text_path),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        opset_version=args.opset,
    )
    print(f"exported text -> {text_path}")
    _write_manifest(onnx_dir, variant, embedding_dimension, image_size)


if __name__ == "__main__":
    main()
