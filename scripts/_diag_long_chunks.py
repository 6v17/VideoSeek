"""Diagnose long semantic chunks for one Lance-backed video."""

from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.app.config import load_config
from src.core.semantic_chunking import (
    SemanticChunkStreamBuilder,
    build_semantic_chunks,
    chunk_builder_kwargs,
    cosine_similarity,
)
from src.storage.config_store import build_chunk_config, get_local_model_asset_dirs
from src.storage.lance_search_index import load_lance_video_frame_arrays


def _analyze_segment(vectors, timestamps, start, end):
    start_idx = int(np.searchsorted(timestamps, start))
    end_idx = int(np.searchsorted(timestamps, end, side="right")) - 1
    seg_v = vectors[start_idx : end_idx + 1]
    seg_t = timestamps[start_idx : end_idx + 1]
    if len(seg_v) < 2:
        return {}
    adj = [cosine_similarity(seg_v[i], seg_v[i + 1]) for i in range(len(seg_v) - 1)]
    core_anchor = seg_v[0]
    to_anchor = [cosine_similarity(v, core_anchor) for v in seg_v]
    return {
        "frames": len(seg_v),
        "adj_min": min(adj),
        "adj_median": sorted(adj)[len(adj) // 2],
        "adj_max": max(adj),
        "adj_below_best": sum(1 for value in adj if value < 0.9),
        "to_anchor_min": min(to_anchor),
        "to_anchor_median": sorted(to_anchor)[len(to_anchor) // 2],
    }


def _simulate_builder(vectors, timestamps, **kwargs):
    builder = SemanticChunkStreamBuilder(**chunk_builder_kwargs(kwargs))
    builder.extend(vectors, timestamps)
    return builder.finish()


def main():
    video_id = sys.argv[1] if len(sys.argv) > 1 else "41963f7591040824cc2460b096c7830fb60da26ad5eda6b12c9acc638007ffed"
    config = load_config()
    chunk_config = build_chunk_config(config)
    model_dirs = get_local_model_asset_dirs(config=config)
    vectors, timestamps = load_lance_video_frame_arrays(model_dirs["base_dir"], video_id)
    print("video_id", video_id)
    print("chunk_config", chunk_config)
    print("frames", len(vectors), "duration_s", float(timestamps[-1] - timestamps[0]))

    chunks = build_semantic_chunks(vectors, timestamps, **chunk_builder_kwargs(chunk_config))
    durations = [float(chunk["end"]) - float(chunk["start"]) for chunk in chunks]
    print("chunks", len(chunks))
    if durations:
        print("max_dur_s", max(durations))
        print("p95_dur_s", sorted(durations)[int(len(durations) * 0.95)])

    long_chunks = [(index, chunk) for index, chunk in enumerate(chunks) if chunk["end"] - chunk["start"] > 30]
    print("chunks_gt_30s", len(long_chunks))
    for index, chunk in long_chunks[:8]:
        duration = chunk["end"] - chunk["start"]
        stats = _analyze_segment(vectors, timestamps, chunk["start"], chunk["end"])
        print(
            f"  #{index} {chunk['start']:.1f}-{chunk['end']:.1f}s dur={duration:.1f}s "
            f"frames={stats.get('frames')} adj_min={stats.get('adj_min', 0):.3f} "
            f"adj_below_0.9={stats.get('adj_below_best', 0)} "
            f"to_anchor_min={stats.get('to_anchor_min', 0):.3f}"
        )

    if long_chunks:
        worst_index, worst = max(enumerate(chunks), key=lambda item: item[1]["end"] - item[1]["start"])
        print("worst_chunk_index", worst_index)
        stats = _analyze_segment(vectors, timestamps, worst["start"], worst["end"])
        print("worst_stats", stats)


if __name__ == "__main__":
    main()
