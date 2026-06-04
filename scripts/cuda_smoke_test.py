"""CUDA ORT smoke test — run before wiring CUDA into the GUI indexing path.

Usage (VideoSeek-CUDA env with onnxruntime-gpu installed):

    $env:VIDEOSEEK_INFERENCE_EP = "cuda"
    python scripts/cuda_smoke_test.py
    python scripts/cuda_smoke_test.py --use-active-profile
    python scripts/cuda_smoke_test.py --profile chinese_clip_vit_base_patch16
"""
from __future__ import annotations

import argparse
import os
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np


def _find_profile(config, profile_id: str) -> dict:
    profiles = list((config.get("models") or {}).get("profiles") or [])
    for profile in profiles:
        if str(profile.get("id", "") or "").strip() == profile_id:
            return dict(profile)
    known = ", ".join(str(p.get("id", "") or "").strip() for p in profiles if isinstance(p, dict))
    raise SystemExit(f"Profile not found: {profile_id}. Known profiles: {known or '(none)'}")


def _resolve_profile_model_paths(config, profile: dict) -> tuple[str, str, str]:
    from src.storage.config_store import resolve_model_resource_dir
    from src.utils import get_default_model_dir

    runtime = dict(profile.get("runtime") or {})
    model_root = str(runtime.get("model_dir") or config.get("model_dir") or "").strip() or get_default_model_dir()
    provider = str(profile.get("provider") or "").strip()
    variant = str(runtime.get("model_variant") or profile.get("model_variant") or "").strip() or "vit-base-patch32"
    resource_dir = resolve_model_resource_dir(model_root, provider, variant)
    files = dict(profile.get("files") or {})
    visual_name = str(
        files.get("visual_model")
        or files.get("image_model")
        or files.get("vision_model")
        or "clip_visual.onnx"
    ).strip()
    text_name = str(files.get("text_model") or "clip_text.onnx").strip()
    visual_path = os.path.join(resource_dir, visual_name)
    text_path = os.path.join(resource_dir, text_name)
    return resource_dir, visual_path, text_path


def _onnx_elem_type_to_numpy(elem_type: str):
    normalized = str(elem_type or "").strip().lower()
    if "int64" in normalized:
        return np.int64
    if "int32" in normalized:
        return np.int32
    if "float16" in normalized:
        return np.float16
    return np.float32


def _dummy_feed(session, *, batch_size: int = 1) -> dict[str, np.ndarray]:
    feeds: dict[str, np.ndarray] = {}
    for inp in session.get_inputs():
        shape = []
        for index, dim in enumerate(inp.shape):
            if dim in (None, "batch", "N"):
                shape.append(batch_size if index == 0 else 1)
            elif isinstance(dim, str):
                shape.append(batch_size if index == 0 else 1)
            else:
                shape.append(int(dim))
        if len(shape) == 4 and shape[0] == 1:
            shape[0] = batch_size
        dtype = _onnx_elem_type_to_numpy(inp.type)
        feeds[inp.name] = np.zeros(shape, dtype=dtype)
    return feeds


def _print_missing_models(profile_id: str, resource_dir: str, visual_path: str, text_path: str, config) -> None:
    active_id = str((config.get("models") or {}).get("active_profile") or "").strip()
    missing = [path for path in (visual_path, text_path) if not os.path.isfile(path)]
    print("FAIL: missing model files for profile:", profile_id)
    print("model_dir:", resource_dir)
    print("visual:", visual_path, "exists=" + str(os.path.isfile(visual_path)))
    print("text:", text_path, "exists=" + str(os.path.isfile(text_path)))
    if active_id and active_id != profile_id:
        print("active_profile:", active_id, "(differs from smoke-test profile)")
    if missing:
        print("Hint: default smoke test uses clip_onnx_default.")
        print("Try: python scripts/cuda_smoke_test.py --use-active-profile")
        print("Or switch active profile in app settings to CLIP ONNX.")


def main() -> int:
    parser = argparse.ArgumentParser(description="CUDA ORT smoke test for VideoSeek model profiles.")
    parser.add_argument(
        "--profile",
        default="clip_onnx_default",
        help="Model profile id to test (default: clip_onnx_default).",
    )
    parser.add_argument(
        "--use-active-profile",
        action="store_true",
        help="Use the active profile from %LOCALAPPDATA%\\VideoSeek\\config.json instead of --profile.",
    )
    args = parser.parse_args()

    os.environ.setdefault("VIDEOSEEK_INFERENCE_EP", "cuda")

    from src.core.inference_providers import (
        ensure_cuda_runtime_dll_paths,
        preferred_gpu_provider_name,
        resolve_ort_providers,
    )

    ensure_cuda_runtime_dll_paths()
    import onnxruntime as ort

    from src.app.config import load_config

    config = load_config()
    profile_id = str((config.get("models") or {}).get("active_profile") or "").strip()
    if args.use_active_profile:
        if not profile_id:
            print("FAIL: no active_profile in config")
            return 1
    else:
        profile_id = str(args.profile or "clip_onnx_default").strip()

    profile = _find_profile(config, profile_id)
    resource_dir, visual_path, text_path = _resolve_profile_model_paths(config, profile)
    if not os.path.isfile(visual_path) or not os.path.isfile(text_path):
        _print_missing_models(profile_id, resource_dir, visual_path, text_path, config)
        return 1

    available = list(ort.get_available_providers())
    print("ort_version:", ort.__version__)
    print("available_providers:", available)
    print("inference_ep_mode:", os.environ.get("VIDEOSEEK_INFERENCE_EP", "dml"))
    print("profile_id:", profile_id)
    print("provider:", profile.get("provider"))
    print("model_dir:", resource_dir)
    print("preferred_gpu_provider:", preferred_gpu_provider_name())

    preferred = preferred_gpu_provider_name()
    if preferred not in available:
        print(f"FAIL: {preferred} not in available providers")
        return 1

    providers = resolve_ort_providers(prefer_gpu=True)
    print("session_providers:", providers)

    visual = ort.InferenceSession(visual_path, providers=providers)
    text = ort.InferenceSession(text_path, providers=providers)
    print("visual_active:", visual.get_providers())
    print("text_active:", text.get_providers())

    if preferred not in visual.get_providers():
        print("FAIL: visual session did not activate", preferred)
        return 1
    if preferred not in text.get_providers():
        print("FAIL: text session did not activate", preferred)
        return 1

    visual_feed = _dummy_feed(visual, batch_size=16)
    t0 = time.perf_counter()
    visual.run(None, visual_feed)
    visual_ms = (time.perf_counter() - t0) * 1000.0
    print(f"visual_batch16_ms: {visual_ms:.1f}")

    text_feed = _dummy_feed(text, batch_size=1)
    t0 = time.perf_counter()
    text.run(None, text_feed)
    text_ms = (time.perf_counter() - t0) * 1000.0
    print(f"text_encode_ms: {text_ms:.1f}")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
