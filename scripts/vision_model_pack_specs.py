"""Shared specs for official 224px large vision model packages.

Used by export / pack scripts. Dimensions must match projected CLIP/SigLIP features
(not the encoder hidden size).
"""

from __future__ import annotations

from typing import Any

# Three 224 large packs requested for VideoSeek releases.
LARGE_224_PACKS: list[dict[str, Any]] = [
    {
        "key": "chinese-clip-vit-large-patch14",
        "provider": "chinese_clip_onnx",
        "provider_dir": "chinese-clip",
        "variant": "vit-large-patch14",
        "hf_id": "OFA-Sys/chinese-clip-vit-large-patch14",
        "embedding_dimension": 512,
        "image_size": 224,
        "display_name": "Chinese CLIP vit-large-patch14",
    },
    {
        "key": "openai-clip-vit-large-patch14",
        "provider": "clip_onnx",
        "provider_dir": "openai-clip",
        "variant": "vit-large-patch14",
        "hf_id": "openai/clip-vit-large-patch14",
        "embedding_dimension": 768,
        "image_size": 224,
        "display_name": "OpenAI CLIP vit-large-patch14",
        "bpe_url": (
            "https://github.com/openai/CLIP/raw/main/clip/bpe_simple_vocab_16e6.txt.gz"
        ),
    },
    {
        "key": "siglip2-so400m-patch14-224",
        "provider": "siglip2_onnx",
        "provider_dir": "siglip2",
        "variant": "so400m-patch14-224",
        "hf_id": "google/siglip2-so400m-patch14-224",
        "embedding_dimension": 1152,
        "image_size": 224,
        "display_name": "SigLIP2 so400m-patch14-224",
    },
]


def get_pack_spec(key_or_variant: str) -> dict[str, Any]:
    needle = str(key_or_variant or "").strip().lower()
    if not needle:
        raise KeyError("pack key/variant is required")

    # Prefer exact key / hf id matches before shared variant names
    # (e.g. both OpenAI and Chinese CLIP use vit-large-patch14).
    for item in LARGE_224_PACKS:
        if needle == str(item["key"]).lower() or needle == str(item["hf_id"]).lower():
            return dict(item)

    variant_hits = [
        item for item in LARGE_224_PACKS if needle == str(item["variant"]).lower()
    ]
    if len(variant_hits) == 1:
        return dict(variant_hits[0])
    if len(variant_hits) > 1:
        keys = ", ".join(item["key"] for item in variant_hits)
        raise KeyError(
            f"Ambiguous pack variant {key_or_variant!r}; use one of: {keys}"
        )

    known = ", ".join(item["key"] for item in LARGE_224_PACKS)
    raise KeyError(f"Unknown pack {key_or_variant!r}. Known: {known}")
