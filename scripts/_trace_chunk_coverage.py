"""Trace which frames are assigned to semantic chunks."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.app.config import load_config
from src.core.semantic_chunking import SemanticChunkStreamBuilder, chunk_builder_kwargs
from src.storage.config_store import build_chunk_config, get_local_model_asset_dirs
from src.storage.lance_search_index import load_lance_video_frame_arrays


def main():
    video_id = sys.argv[1] if len(sys.argv) > 1 else "41963f7591040824cc2460b096c7830fb60da26ad5eda6b12c9acc638007ffed"
    config = load_config()
    chunk_config = build_chunk_config(config)
    model_dirs = get_local_model_asset_dirs(config=config)
    vectors, timestamps = load_lance_video_frame_arrays(model_dirs["base_dir"], video_id)

    builder = SemanticChunkStreamBuilder(**chunk_builder_kwargs(chunk_config))
    builder.extend(vectors, timestamps)
    chunks = builder.finish()

    assigned = [-1] * len(timestamps)
    offset = 0
    for chunk_index, record in enumerate(builder.chunks):
        for time in record["times"]:
            while offset < len(timestamps) and float(timestamps[offset]) < float(time) - 1e-6:
                offset += 1
            if offset < len(timestamps) and abs(float(timestamps[offset]) - float(time)) <= 1e-3:
                assigned[offset] = chunk_index
                offset += 1

    missing = [index for index, value in enumerate(assigned) if value < 0]
    print("frames", len(timestamps), "chunks", len(chunks), "missing", len(missing))
    if missing:
        print("first missing indices", missing[:20])
        for index in missing[:8]:
            print(
                f"  frame {index} t={float(timestamps[index]):.1f} "
                f"prev_t={float(timestamps[index-1]):.1f if index else 'n/a'}"
            )


if __name__ == "__main__":
    main()
