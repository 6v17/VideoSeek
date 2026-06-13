"""One-off library vector health report (run with conda VideoSeek env)."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.app.config import load_config
from src.core.faiss_index import load_clip_index, load_vectors
from src.storage.config_store import get_local_model_asset_dirs


def _read_vector_health(vector_file: str) -> tuple[bool, bool]:
    if not os.path.exists(vector_file):
        return False, False
    try:
        data = load_vectors(vector_file)
    except Exception:
        return True, False
    if not isinstance(data, dict):
        return True, False
    vectors = data.get("vector")
    timestamps = data.get("timestamps")
    if vectors is None or timestamps is None:
        return True, False
    try:
        vector_count = len(vectors)
        timestamp_count = len(timestamps)
    except TypeError:
        return True, False
    if vector_count <= 0 or vector_count != timestamp_count:
        return True, False
    return True, True


def _read_index_health(index_file: str) -> tuple[bool, bool]:
    if not os.path.exists(index_file):
        return False, False
    try:
        return True, load_clip_index(index_file) is not None
    except Exception:
        return True, False


def _effective_asset_state(info, *, source_exists, vector_exists, vector_ok, index_exists, index_ok):
    stored_state = str(info.get("asset_state", "")).strip().lower()
    if not source_exists:
        return "missing_source"
    if stored_state == "sync_failed" and (not vector_exists or not vector_ok or not index_exists or not index_ok):
        return "sync_failed"
    if not vector_exists or not index_exists:
        return "missing_asset"
    if not vector_ok or not index_ok:
        return "broken_asset"
    return "ready"


def _sample_vector_stats(vector_file: str) -> dict:
    try:
        data = load_vectors(vector_file)
    except Exception as exc:
        return {"error": str(exc)}
    vectors = data.get("vector")
    timestamps = data.get("timestamps")
    try:
        v_count = len(vectors)
        t_count = len(timestamps)
    except TypeError:
        return {"error": "vector/timestamps not sized"}
    shape = getattr(vectors, "shape", None)
    return {
        "vector_count": v_count,
        "timestamp_count": t_count,
        "shape": tuple(shape) if shape is not None else None,
        "match": v_count == t_count and v_count > 0,
    }


def main() -> None:
    cfg = load_config()
    print("=== Config ===")
    print("data_root:", cfg.get("data_root"))
    print("search_mode:", cfg.get("search_mode"))
    print("search_scope_mode:", cfg.get("search_scope_mode"))
    print("active_model:", ((cfg.get("models") or {}).get("active_profile")))

    dirs = get_local_model_asset_dirs(config=cfg)
    meta_file = dirs.get("meta_file")
    vector_dir = dirs.get("vector_dir")
    index_dir = dirs.get("index_dir")
    print("meta_file:", meta_file)
    print("vector_dir:", vector_dir)
    print("index_dir:", index_dir)
    print("meta_exists:", os.path.isfile(meta_file or ""))
    print("vector_dir_exists:", os.path.isdir(vector_dir or ""))
    print("index_dir_exists:", os.path.isdir(index_dir or ""))

    if not meta_file or not os.path.isfile(meta_file):
        print("ERROR: meta.json not found; cannot inspect libraries.")
        return

    with open(meta_file, "r", encoding="utf-8") as handle:
        meta = json.load(handle)
    print("global_index_state:", meta.get("global_index_state"))
    print("search_index_schema_version:", meta.get("search_index_schema_version"))

    libraries = meta.get("libraries") or {}
    print("=== Libraries ===")
    print("count:", len(libraries))
    entries = []
    for library_path, library_data in libraries.items():
        files = library_data.get("files") or {}
        states = Counter(
            str((info or {}).get("asset_state", "") or "unknown").lower()
            for info in files.values()
        )
        print(f"  {library_path}")
        print("    files:", len(files), dict(states))
        print("    index_state:", library_data.get("index_state"))
        for rel_path, info in files.items():
            video_id = str((info or {}).get("vid", "")).strip()
            if not video_id:
                continue
            video_path = os.path.normpath(os.path.join(library_path, rel_path))
            vector_file = os.path.normpath(os.path.join(vector_dir, f"{video_id}_vectors.npy"))
            index_file = os.path.normpath(os.path.join(index_dir, f"{video_id}_index.faiss"))
            source_exists = os.path.exists(video_path)
            vector_exists, vector_ok = _read_vector_health(vector_file)
            index_exists, index_ok = _read_index_health(index_file)
            asset_state = _effective_asset_state(
                info or {},
                source_exists=source_exists,
                vector_exists=vector_exists,
                vector_ok=vector_ok,
                index_exists=index_exists,
                index_ok=index_ok,
            )
            entries.append(
                {
                    "library_path": library_path,
                    "video_rel_path": rel_path,
                    "video_id": video_id,
                    "asset_state": asset_state,
                    "source_exists": source_exists,
                    "vector_exists": vector_exists,
                    "vector_ok": vector_ok,
                    "index_exists": index_exists,
                    "index_ok": index_ok,
                    "vector_file": vector_file,
                    "index_file": index_file,
                }
            )

    print("=== Vector entries (validated) ===")
    print("total:", len(entries))
    state_counts = Counter(e.get("asset_state") for e in entries)
    print("by_state:", dict(state_counts))

    problems = [e for e in entries if e.get("asset_state") != "ready"]
    print("problem_count:", len(problems))
    for e in problems[:40]:
        print(
            "  -",
            e.get("video_rel_path"),
            "|",
            e.get("asset_state"),
            "| src=",
            e.get("source_exists"),
            "vec=",
            e.get("vector_exists"),
            "vec_ok=",
            e.get("vector_ok"),
            "idx=",
            e.get("index_exists"),
            "idx_ok=",
            e.get("index_ok"),
        )

    ready = [e for e in entries if e.get("asset_state") == "ready"]
    print("=== Ready vector samples (up to 5) ===")
    for e in ready[:5]:
        print(" ", e.get("video_rel_path"), _sample_vector_stats(e.get("vector_file", "")))

    vec_files = (
        [f for f in os.listdir(vector_dir) if f.endswith("_vectors.npy")]
        if vector_dir and os.path.isdir(vector_dir)
        else []
    )
    idx_files = (
        [f for f in os.listdir(index_dir) if f.endswith("_index.faiss")]
        if index_dir and os.path.isdir(index_dir)
        else []
    )
    known_vids = {e.get("video_id") for e in entries if e.get("video_id")}
    orphan_vec = [f for f in vec_files if f.replace("_vectors.npy", "") not in known_vids]
    orphan_idx = [f for f in idx_files if f.replace("_index.faiss", "") not in known_vids]
    print("=== Orphans ===")
    print("vector_files:", len(vec_files), "orphan_vectors:", len(orphan_vec))
    print("index_files:", len(idx_files), "orphan_indexes:", len(orphan_idx))
    if orphan_vec[:5]:
        print("  orphan_vec sample:", orphan_vec[:5])
    if orphan_idx[:5]:
        print("  orphan_idx sample:", orphan_idx[:5])

    from src.storage.config_store import get_active_embedding_spec

    expected_spec = get_active_embedding_spec(config=cfg)
    bad = []
    dims: set[int] = set()
    for e in entries:
        if e.get("asset_state") != "ready":
            continue
        rel = e.get("video_rel_path")
        try:
            data = load_vectors(e.get("vector_file", ""))
            spec = data.get("embedding_spec") if isinstance(data, dict) else None
            vec = data.get("vector")
            dim = int(getattr(vec, "shape", [0, 0])[1]) if vec is not None else 0
            dims.add(dim)
            idx = load_clip_index(e.get("index_file", ""))
            idim = int(getattr(idx, "d", 0) or 0)
            issues = []
            if spec != expected_spec:
                issues.append("spec_mismatch")
            if dim != int(expected_spec.get("dimension") or 0):
                issues.append(f"dim={dim}")
            if idim and idim != int(expected_spec.get("dimension") or 0):
                issues.append(f"index_dim={idim}")
            if len(vec) != len(data.get("timestamps", [])):
                issues.append("ts_mismatch")
            if issues:
                bad.append((rel, issues))
        except Exception as exc:
            bad.append((rel, [f"error:{exc}"]))
    print("=== Full scan (ready entries) ===")
    print("expected_spec:", expected_spec)
    print("unique_dims:", sorted(dims))
    print("bad_count:", len(bad))
    for row in bad[:20]:
        print(" ", row)


if __name__ == "__main__":
    main()
