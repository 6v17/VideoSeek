"""Debug chunk splits for a video's stored frame vectors."""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.app.config import load_config
from src.core.semantic_chunking import build_semantic_chunks, chunk_builder_kwargs
from src.storage.asset_store import load_vector_payload
from src.storage.config_store import build_chunk_config


def _run(video_id: str, vector_file: str, config_overrides: dict | None = None):
    config = load_config()
    if config_overrides:
        config.update(config_overrides)
    chunk_config = build_chunk_config(config)
    payload = load_vector_payload(vector_file)
    vectors = payload.get("vector")
    timestamps = payload.get("timestamps")
    if vectors is None or timestamps is None:
        raise RuntimeError(f"No vectors in {vector_file}")

    chunks = build_semantic_chunks(vectors, timestamps, **chunk_builder_kwargs(chunk_config))
    print(f"video={video_id} config={chunk_config} chunks={len(chunks)}")
    for index, chunk in enumerate(chunks):
        print(
            f"  [{index}] {chunk['start']:.2f}s - {chunk['end']:.2f}s "
            f"({chunk['end'] - chunk['start']:.2f}s)"
        )
    return chunks


def main():
    parser = argparse.ArgumentParser(description="Debug semantic chunk splits")
    parser.add_argument("vector_file", help="Path to vector .npz file")
    parser.add_argument("--video-id", default="debug", help="Label for output")
    parser.add_argument("--similarity-threshold", type=float, default=None)
    args = parser.parse_args()

    overrides = {}
    if args.similarity_threshold is not None:
        overrides["similarity_threshold"] = args.similarity_threshold
    _run(args.video_id, args.vector_file, overrides or None)


if __name__ == "__main__":
    main()
