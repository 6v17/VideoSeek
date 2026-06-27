"""Sanity check: extract one indexed frame and image-search it back."""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from src.app.config import load_config
from src.core.faiss_index import load_vectors
from src.core.image_io import load_image_bgr
from src.services.search_service import build_query_vector, run_search
from src.storage.asset_store import load_model_metadata
from src.storage.config_store import get_local_model_asset_dirs
from src.utils import get_single_thumbnail


def _first_ready_entry(meta, vector_dir):
    for lib_path, lib in (meta.get("libraries") or {}).items():
        for rel, info in (lib.get("files") or {}).items():
            if str(info.get("asset_state", "")).lower() != "ready":
                continue
            vid = str(info.get("vid", "")).strip()
            if not vid:
                continue
            video_path = os.path.join(lib_path, rel)
            vector_file = os.path.join(vector_dir, f"{vid}_vectors.npy")
            if not os.path.isfile(vector_file):
                continue
            data = load_vectors(vector_file)
            ts = data.get("timestamps")
            if ts is None:
                continue
            ts_len = len(ts)
            if ts_len < 10:
                continue
            pick = ts_len // 3
            return {
                "video_path": video_path,
                "rel": rel,
                "time_sec": float(ts[pick]),
                "vector_file": vector_file,
            }
    return None


def main() -> None:
    cfg = load_config()
    dirs = get_local_model_asset_dirs(config=cfg)
    meta = load_model_metadata(config=cfg)
    entry = _first_ready_entry(meta, dirs["vector_dir"])
    if not entry:
        print("No ready indexed video found.")
        return

    print("probe_video:", entry["rel"])
    print("probe_time:", entry["time_sec"])

    frame = get_single_thumbnail(entry["video_path"], entry["time_sec"])
    if frame is None:
        print("ERROR: could not decode probe frame")
        return

    tmp = os.path.join(os.environ.get("TEMP", "."), "videoseek_probe_frame.jpg")
    import cv2

    cv2.imwrite(tmp, frame)
    print("probe_image:", tmp)

    q_fast = build_query_vector(tmp, is_text=False)
    print("query_vector_shape:", tuple(q_fast.shape))

    for mode in ("fast", "precise"):
        hits = run_search(
            query_data=tmp,
            is_text=False,
            top_k=5,
            search_mode="frame",
            search_precision_mode=mode,
        )
        print(f"=== full frame search mode={mode} top5 ===")
        for i, hit in enumerate(hits[:5], 1):
            name = os.path.basename(str(hit.video_path))
            print(
                f"  {i}. score={float(hit.score):.4f} t={float(hit.start_sec):.2f}s "
                f"kind={getattr(hit, 'match_kind', 'frame')} file={name}"
            )
        if hits:
            top = hits[0]
            same = os.path.normcase(str(top.video_path)) == os.path.normcase(str(entry["video_path"]))
            dt = abs(float(top.start_sec) - float(entry["time_sec"]))
            print(f"  top1_same_video={same} time_delta_sec={dt:.2f}")

    h, w = frame.shape[:2]
    crop = frame[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
    crop_path = os.path.join(os.environ.get("TEMP", "."), "videoseek_probe_crop.jpg")
    cv2.imwrite(crop_path, crop)
    print("crop_size:", crop.shape[1], "x", crop.shape[0])

    from src.services.image_search_rerank import is_likely_cropped_query_image

    print("is_likely_cropped_query_image:", is_likely_cropped_query_image(crop_path))

    for mode in ("fast", "precise"):
        hits = run_search(
            query_data=crop_path,
            is_text=False,
            top_k=5,
            search_mode="frame",
            search_precision_mode=mode,
        )
        print(f"=== cropped screenshot search mode={mode} top5 ===")
        for i, hit in enumerate(hits[:5], 1):
            name = os.path.basename(str(hit.video_path))
            print(
                f"  {i}. score={float(hit.score):.4f} t={float(hit.start_sec):.2f}s "
                f"kind={getattr(hit, 'match_kind', 'frame')} file={name}"
            )
        if hits:
            top = hits[0]
            same = os.path.normcase(str(top.video_path)) == os.path.normcase(str(entry["video_path"]))
            dt = abs(float(top.start_sec) - float(entry["time_sec"]))
            print(f"  top1_same_video={same} time_delta_sec={dt:.2f}")

    for path in (tmp, crop_path):
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
