"""Smoke test: NVDEC native decode -> GPU preprocess -> ORT CUDA input binding."""
from __future__ import annotations

import argparse
import os
import sys
import time


def _bootstrap_import_path():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)


def main():
    parser = argparse.ArgumentParser(description="CUDA zero-copy indexing smoke test")
    parser.add_argument("video", help="Path to a short test video")
    parser.add_argument("--frames", type=int, default=8, help="Number of sampled frames to encode")
    parser.add_argument("--fps", type=float, default=1.0, help="Sampling FPS for NVDEC stream")
    args = parser.parse_args()

    _bootstrap_import_path()
    os.environ.setdefault("VIDEOSEEK_INFERENCE_EP", "cuda")
    os.environ.setdefault("VIDEOSEEK_CUDA_ZERO_COPY", "1")
    if not os.environ.get("CUDA_PATH"):
        for candidate in (
            r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2",
            r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6",
            r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4",
        ):
            if os.path.isdir(candidate):
                os.environ["CUDA_PATH"] = candidate
                break

    from src.core.gpu_clip_preprocess import _ensure_cupy_cuda_context
    _ensure_cupy_cuda_context(0)

    from src.core.extract_frames import cuda_zero_copy_indexing_enabled, pynvvideocodec_available, cupy_available
    from src.core.nvdec_cuda_decoder import stream_frames_nvdec_cuda_with_fallback
    from src.core.gpu_clip_preprocess import load_mean_std_from_engine, preprocess_batch_gpu
    import src.core.clip_embedding  # noqa: F401 — registers clip_onnx / chinese_clip_onnx / siglip2_onnx
    from src.core.inference_registry import build_inference_engine
    from src.storage.config_store import get_active_model_profile
    from src.app.config import load_config

    print("pynvvideocodec:", pynvvideocodec_available())
    print("cupy:", cupy_available())
    print("zero_copy:", cuda_zero_copy_indexing_enabled())
    if not cuda_zero_copy_indexing_enabled():
        raise SystemExit("CUDA zero-copy prerequisites are not available")

    config = load_config()
    profile = get_active_model_profile(config=config)
    provider = str(profile.get("provider", "") or "clip_onnx").strip() or "clip_onnx"
    engine = build_inference_engine(provider)
    print("provider:", provider)

    frames = []
    timestamps = []
    t0 = time.perf_counter()
    for frame, ts in stream_frames_nvdec_cuda_with_fallback(args.video, float(args.fps)):
        frames.append(frame)
        timestamps.append(ts)
        if len(frames) >= max(1, int(args.frames)):
            break
    decode_s = time.perf_counter() - t0
    print(f"decoded {len(frames)} gpu frames in {decode_s:.2f}s")

    t1 = time.perf_counter()
    mean, std = load_mean_std_from_engine(engine)
    gpu_batch = preprocess_batch_gpu(
        frames,
        image_size=int(getattr(engine, "image_size", 224) or 224),
        mean=mean,
        std=std,
    )
    pre_s = time.perf_counter() - t1
    print(f"gpu preprocess shape={tuple(int(x) for x in gpu_batch.shape)} in {pre_s:.2f}s")

    t2 = time.perf_counter()
    vectors = engine.encode_preprocessed_batch_gpu(gpu_batch)
    ort_s = time.perf_counter() - t2
    from src.core.gpu_vector_ops import gpu_to_numpy, is_cupy_array

    if is_cupy_array(vectors):
        print(f"encoded vectors gpu shape={tuple(int(x) for x in vectors.shape)} in {ort_s:.2f}s (full GPU ORT output)")
        vectors = gpu_to_numpy(vectors)
    print(f"encoded vectors cpu shape={vectors.shape}")
    print("done")


if __name__ == "__main__":
    main()
