"""Quick check that Lance search loads the user's imported profile."""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.app.config import load_config
from src.services.search_assets import load_chunk_search_assets, load_search_assets
from src.storage.config_store import get_local_model_asset_dirs
from src.storage.lance_store import should_use_lance_search


def main() -> int:
    config = load_config()
    model_dirs = get_local_model_asset_dirs(config=config)
    print("profile_base_dir:", model_dirs["base_dir"])
    print("use_lance:", should_use_lance_search(config))
    frame_index, timestamps, paths = load_search_assets(config)
    chunk_index, ranges, chunk_paths = load_chunk_search_assets(config)
    print("frame_index:", None if frame_index is None else frame_index.ntotal)
    print("chunk_index:", None if chunk_index is None else chunk_index.ntotal)
    print("timestamps:", 0 if timestamps is None else len(timestamps))
    print("chunk_ranges:", 0 if ranges is None else len(ranges))
    return 0 if frame_index is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
