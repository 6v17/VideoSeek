"""Check sync status for one library path."""
from __future__ import annotations

import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import lancedb

from src.app.config import load_config
from src.storage.asset_store import load_metadata
from src.storage.config_store import get_local_model_asset_dirs
from src.storage.lance_store import get_lance_dir, should_use_lance_storage
from src.utils import canonicalize_library_path


def main() -> int:
    library_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\LiuWei\Desktop\新建文件夹"
    config = load_config()
    model_dirs = get_local_model_asset_dirs(config=config)
    meta = load_metadata(model_dirs["meta_file"])
    lib_key = canonicalize_library_path(library_path)

    matched = None
    for root, data in (meta.get("libraries") or {}).items():
        if canonicalize_library_path(root) == lib_key:
            matched = (root, data)
            break

    print("profile:", model_dirs["base_dir"])
    print("lance_storage:", should_use_lance_storage(config))
    print("library:", library_path)
    print("matched:", matched[0] if matched else None)

    if not matched:
        return 1

    files = matched[1].get("files") or {}
    ready = []
    failed = []
    for rel, info in files.items():
        state = str(info.get("asset_state", "")).strip().lower()
        vid = str(info.get("vid", "") or "").strip()
        if state == "ready":
            ready.append((rel, vid))
        else:
            failed.append((rel, state, vid))

    print("ready:", len(ready), "other:", len(failed))
    vector_dir = model_dirs["vector_dir"]
    index_dir = model_dirs["index_dir"]
    new_npy = []
    new_faiss = []
    for rel, vid in ready:
        npy = os.path.join(vector_dir, f"{vid}_vectors.npy")
        faiss = os.path.join(index_dir, f"{vid}_index.faiss")
        if os.path.isfile(npy):
            mtime = datetime.fromtimestamp(os.path.getmtime(npy))
            new_npy.append((rel, mtime.isoformat(timespec="seconds")))
        if os.path.isfile(faiss):
            mtime = datetime.fromtimestamp(os.path.getmtime(faiss))
            new_faiss.append((rel, mtime.isoformat(timespec="seconds")))

    print("ready_with_npy:", len(new_npy))
    print("ready_with_faiss:", len(new_faiss))
    for item in new_npy[:5]:
        print("  npy", item)
    for item in new_faiss[:5]:
        print("  faiss", item)

    lance_dir = get_lance_dir(model_dirs["base_dir"])
    db = lancedb.connect(lance_dir)
    frames = db.open_table("frames")
    chunks = db.open_table("chunks") if "chunks" in db.list_tables().tables else None
    import pyarrow.compute as pc

    arrow = frames.to_arrow()
    mask = pc.equal(arrow["library_path"], lib_key)
    lib_frames = arrow.filter(mask)
    print("lance_frames_for_library:", lib_frames.num_rows)
    if lib_frames.num_rows > 0:
        video_ids = sorted(set(lib_frames["video_id"].to_pylist()))
        print("lance_video_ids:", len(video_ids))
        for vid in video_ids[:5]:
            print(" ", vid[:16] + "...")

    if chunks is not None:
        chunk_arrow = chunks.to_arrow()
        chunk_mask = pc.equal(chunk_arrow["library_path"], lib_key)
        lib_chunks = chunk_arrow.filter(chunk_mask)
        print("lance_chunks_for_library:", lib_chunks.num_rows)

    state_file = os.path.join(lance_dir, "import_state.json")
    if os.path.isfile(state_file):
        import json

        with open(state_file, "r", encoding="utf-8") as handle:
            print("import_state:", json.load(handle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
