import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.app.config import load_config
from src.core.clip_embedding import get_clip_embeddings_batch
from src.core.faiss_index import create_clip_index
from src.utils import get_ffmpeg_path


def main():
    args = parse_args()
    links = load_links(args.links_file)
    if not links:
        raise RuntimeError("No links found in links file.")

    config = load_config()
    fps = args.fps if args.fps > 0 else int(config.get("fps", 1))
    os.makedirs(args.output_dir, exist_ok=True)

    all_vectors = []
    all_timestamps = []
    all_paths = []
    all_source_links = []
    all_titles = []
    existing_keys = set()

    started = time.time()
    out_index = os.path.join(args.output_dir, args.index_name)
    out_vectors = os.path.join(args.output_dir, args.vector_name)
    out_manifest = os.path.join(args.output_dir, args.manifest_name)

    if args.incremental and os.path.exists(out_vectors):
        print(f"Loading existing vectors: {out_vectors}")
        existing = load_existing_payload(out_vectors)
        if existing["vector"].size > 0:
            all_vectors.append(existing["vector"].astype("float32"))
            all_timestamps.extend(existing["timestamps"])
            all_paths.extend(existing["paths"])
            all_source_links.extend(existing["source_links"])
            all_titles.extend(existing["titles"])
            existing_keys = build_existing_keys(existing["paths"], existing["timestamps"])
            print(f"  - loaded {existing['vector'].shape[0]} existing vectors")

    new_vector_blocks = []
    for index, link in enumerate(links, start=1):
        print(f"[{index}/{len(links)}] Preparing source: {link}")
        source = prepare_source(link, mode=args.mode)
        frames, timestamps = extract_frames(
            source["input"],
            fps=fps,
            max_frames=args.max_frames_per_video,
        )
        if not frames:
            print(f"  - skipped: no frames extracted ({source['source_link']})")
            continue

        vectors = get_clip_embeddings_batch(frames).astype("float32")
        if vectors.size == 0:
            print(f"  - skipped: no embeddings ({source['source_link']})")
            continue

        source_id = str(source.get("source_id", "") or source.get("source_link", ""))
        filtered_indices = []
        filtered_timestamps = []
        for local_idx, ts in enumerate(timestamps):
            key = compose_key(source_id, ts)
            if key in existing_keys:
                continue
            existing_keys.add(key)
            filtered_indices.append(local_idx)
            filtered_timestamps.append(float(ts))

        if not filtered_indices:
            print("  - skipped: all frames already indexed")
            continue

        filtered_vectors = vectors[filtered_indices]
        new_vector_blocks.append(filtered_vectors)
        all_vectors.append(filtered_vectors)
        all_timestamps.extend(filtered_timestamps)
        all_paths.extend([source_id] * len(filtered_indices))
        all_source_links.extend([source["source_link"]] * len(filtered_indices))
        all_titles.extend([source.get("title", source["source_link"])] * len(filtered_indices))
        print(f"  - frames: {len(frames)} added: {len(filtered_indices)}")

    if not all_vectors:
        raise RuntimeError("No vectors available after processing.")

    new_vectors_count = int(sum(block.shape[0] for block in new_vector_blocks))
    if args.incremental and new_vectors_count == 0 and os.path.exists(out_index) and not args.force_rebuild:
        print("No new vectors appended. Skipping rebuild.")
        return

    merged_vectors = np.vstack(all_vectors).astype("float32")

    print(f"Building FAISS index: {out_index}")
    create_clip_index(merged_vectors, out_index)

    payload = {
        "vector": merged_vectors,
        "timestamps": np.asarray(all_timestamps, dtype="float32"),
        "paths": np.asarray(all_paths, dtype=object),
        "source_links": np.asarray(all_source_links, dtype=object),
        "titles": np.asarray(all_titles, dtype=object),
    }
    np.save(out_vectors, payload)
    print(f"Saved vectors: {out_vectors}")

    manifest = build_manifest(
        args.base_url,
        files=[
            {"name": args.index_name, "path": out_index},
            {"name": args.vector_name, "path": out_vectors},
        ],
        version=args.version,
        total_vectors=int(merged_vectors.shape[0]),
    )
    with open(out_manifest, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
    print(f"Saved manifest: {out_manifest}")
    print(f"Done in {time.time() - started:.2f}s | new={new_vectors_count} total={merged_vectors.shape[0]}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build remote vector library from online video links.",
    )
    parser.add_argument(
        "--links-file",
        required=True,
        help="Text file with one video link per line.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join("data", "remote_pack"),
        help="Output folder for index/vector/manifest files.",
    )
    parser.add_argument(
        "--mode",
        choices=["download", "stream"],
        default="download",
        help="download: save local file first; stream: resolve direct stream URL.",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=0,
        help="Frame sampling FPS. 0 means use config fps.",
    )
    parser.add_argument(
        "--max-frames-per-video",
        type=int,
        default=300,
        help="Hard limit of sampled frames per source video.",
    )
    parser.add_argument(
        "--index-name",
        default="remote_index.faiss",
        help="Index output filename.",
    )
    parser.add_argument(
        "--vector-name",
        default="remote_vectors.npy",
        help="Vector output filename.",
    )
    parser.add_argument(
        "--manifest-name",
        default="manifest.json",
        help="Manifest output filename.",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Optional base URL for published files.",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Append only new source_id+timestamp items from links into existing pack.",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Rebuild output files even if incremental mode finds no new vectors.",
    )
    parser.add_argument(
        "--version",
        default="",
        help="Optional version string written to manifest.",
    )
    return parser.parse_args()


def load_links(path):
    links = []
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            links.append(line)
    return links


def prepare_source(link, mode="download"):
    yt_dlp = load_yt_dlp()
    if mode == "download":
        cache_dir = os.path.join("data", "remote_build_cache")
        os.makedirs(cache_dir, exist_ok=True)
        options = {
            "format": "mp4/bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "outtmpl": os.path.join(cache_dir, "%(id)s_%(title).80s.%(ext)s"),
            "restrictfilenames": True,
        }
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(link, download=True)
            output_path = resolve_downloaded_file(info, downloader)
        if not output_path or not os.path.exists(output_path):
            raise RuntimeError(f"Download failed: {link}")
        return {
            "input": output_path,
            "source_link": info.get("webpage_url") or link,
            "title": info.get("title") or link,
            "source_id": info.get("id") or output_path,
        }

    options = {"noplaylist": True, "quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(link, download=False)
    stream_url = info.get("url") or ""
    if not stream_url:
        for fmt in info.get("formats") or []:
            if fmt.get("url"):
                stream_url = fmt["url"]
                break
    if not stream_url:
        raise RuntimeError(f"Stream URL not found: {link}")
    return {
        "input": stream_url,
        "source_link": info.get("webpage_url") or link,
        "title": info.get("title") or link,
        "source_id": info.get("id") or stream_url,
    }


def resolve_downloaded_file(info, downloader):
    for item in info.get("requested_downloads") or []:
        path = item.get("filepath")
        if path and os.path.exists(path):
            return path
    filename = info.get("_filename")
    if filename and os.path.exists(filename):
        return filename
    prepared = downloader.prepare_filename(info)
    if prepared and os.path.exists(prepared):
        return prepared
    base, _ = os.path.splitext(prepared)
    for ext in [".mp4", ".mkv", ".webm", ".mov"]:
        candidate = f"{base}{ext}"
        if os.path.exists(candidate):
            return candidate
    return ""


def extract_frames(source_input, fps=1, max_frames=300):
    ffmpeg_bin = get_ffmpeg_path()
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        source_input,
        "-vf",
        f"fps={max(1, int(fps))},scale=224:224",
        "-sn",
        "-vframes",
        str(max(1, int(max_frames))),
        "-f",
        "image2pipe",
        "-pix_fmt",
        "bgr24",
        "-vcodec",
        "rawvideo",
        "-",
    ]

    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        startupinfo=startupinfo,
    )

    frame_size = 224 * 224 * 3
    frames = []
    timestamps = []
    frame_index = 0
    safe_fps = max(1, int(fps))
    while True:
        if process.stdout is None:
            break
        chunk = process.stdout.read(frame_size)
        if len(chunk) != frame_size:
            break
        frame = np.frombuffer(chunk, np.uint8).reshape((224, 224, 3))
        frames.append(frame)
        timestamps.append(frame_index / safe_fps)
        frame_index += 1

    process.wait(timeout=20)
    return frames, timestamps


def build_manifest(base_url, files, version="", total_vectors=0):
    normalized_base = str(base_url or "").strip().rstrip("/")
    items = []
    for item in files:
        entry = {
            "name": item["name"],
            "sha256": file_sha256(item["path"]),
        }
        if normalized_base:
            entry["url"] = f"{normalized_base}/{item['name']}"
        else:
            entry["url"] = ""
        items.append(entry)
    return {
        "version": str(version).strip() or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_vectors": int(total_vectors),
        "files": items,
    }


def file_sha256(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


def load_yt_dlp():
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise RuntimeError("yt-dlp is not installed. Run: pip install yt-dlp") from exc
    return yt_dlp


def load_existing_payload(path):
    data = np.load(path, allow_pickle=True).item()
    return {
        "vector": np.asarray(data.get("vector", np.empty((0, 0), dtype=np.float32)), dtype=np.float32),
        "timestamps": [float(value) for value in data.get("timestamps", [])],
        "paths": [str(value) for value in data.get("paths", [])],
        "source_links": [str(value) for value in data.get("source_links", [])],
        "titles": [str(value) for value in data.get("titles", [])],
    }


def build_existing_keys(paths, timestamps):
    keys = set()
    count = min(len(paths), len(timestamps))
    for idx in range(count):
        keys.add(compose_key(paths[idx], timestamps[idx]))
    return keys


def compose_key(source_id, timestamp):
    return f"{source_id}::{int(round(float(timestamp) * 1000))}"


if __name__ == "__main__":
    main()
