import os
import re
import subprocess
import time
from typing import Callable
from urllib.parse import urlparse

import numpy as np

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.core.clip_embedding import get_clip_embeddings_batch
from src.services.search_service import load_search_assets
from src.utils import get_ffmpeg_path

logger = get_logger("link_search_service")

ProgressCallback = Callable[[int, str], None]


def run_link_search(link, mode="download", top_k=None, progress_callback=None):
    if not link or not str(link).strip():
        raise ValueError("Video link is required.")
    normalized_link = _normalize_link_input(str(link))

    config = load_config()
    if top_k is None:
        top_k = int(config.get("search_top_k", 20))

    _emit(progress_callback, 5, "Preparing source video...")
    source = _prepare_source(normalized_link, mode=mode)
    source_input = source["input"]

    _emit(progress_callback, 20, "Extracting frames...")
    frames, source_timestamps = _extract_source_frames(
        source_input,
        fps=int(config.get("fps", 1)),
        max_frames=180,
    )
    if not frames:
        raise RuntimeError("No frames extracted from source.")

    _emit(progress_callback, 45, "Generating CLIP embeddings...")
    vectors = get_clip_embeddings_batch(frames).astype("float32")
    if vectors.size == 0:
        raise RuntimeError("Failed to generate embeddings from source frames.")

    _emit(progress_callback, 65, "Loading existing index...")
    search_index, timestamps, video_paths = load_search_assets(config)
    if search_index is None:
        raise RuntimeError("Global frame search index is missing. Update index first.")

    _emit(progress_callback, 80, "Matching vectors against index...")
    results = _search_against_global_index(
        vectors,
        source_timestamps,
        search_index,
        timestamps,
        video_paths,
        top_k=top_k,
        per_frame_k=5,
    )

    _emit(progress_callback, 100, "Match completed.")
    return {
        "results": results,
        "source_link": source["source_link"],
        "source_title": source.get("title", ""),
        "source_mode": mode,
    }


def _prepare_source(link, mode="download"):
    normalized_mode = (mode or "download").lower()
    if normalized_mode not in {"download", "stream"}:
        raise ValueError(f"Unsupported mode: {mode}")
    if normalized_mode == "download":
        return _download_video(link)
    return _resolve_stream(link)


def _download_video(link):
    yt_dlp = _load_yt_dlp()
    cache_dir = os.path.join("data", "link_cache")
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
        output_path = _resolve_downloaded_file(info, downloader)

    if not output_path or not os.path.exists(output_path):
        raise RuntimeError("Video download finished but output file is missing.")

    return {
        "input": output_path,
        "source_link": info.get("webpage_url") or link,
        "title": info.get("title") or "",
    }


def _resolve_stream(link):
    yt_dlp = _load_yt_dlp()
    options = {"noplaylist": True, "quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(link, download=False)

    stream_url = info.get("url") or ""
    if not stream_url:
        formats = info.get("formats") or []
        for candidate in formats:
            candidate_url = candidate.get("url") or ""
            if candidate_url:
                stream_url = candidate_url
                break

    if not stream_url:
        raise RuntimeError("Unable to resolve stream URL from the given link.")

    return {
        "input": stream_url,
        "source_link": info.get("webpage_url") or link,
        "title": info.get("title") or "",
    }


def _resolve_downloaded_file(info, downloader):
    requested = info.get("requested_downloads") or []
    for item in requested:
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
    for extension in [".mp4", ".mkv", ".webm", ".mov"]:
        candidate = f"{base}{extension}"
        if os.path.exists(candidate):
            return candidate
    return ""


def _extract_source_frames(source_input, fps=1, max_frames=180):
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
    frame_count = 0
    safe_fps = max(1, int(fps))
    started = time.time()

    while True:
        if process.stdout is None:
            break
        chunk = process.stdout.read(frame_size)
        if len(chunk) != frame_size:
            break
        frame = np.frombuffer(chunk, np.uint8).reshape((224, 224, 3))
        frames.append(frame)
        timestamps.append(frame_count / safe_fps)
        frame_count += 1

    stderr = b""
    if process.stderr is not None:
        stderr = process.stderr.read()
    process.wait(timeout=15)

    if not frames:
        message = stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(message or "Frame extraction failed.")

    logger.info(
        "Extracted %s frames from source in %.2fs",
        len(frames),
        time.time() - started,
    )
    return frames, timestamps


def _search_against_global_index(
    query_vectors,
    source_timestamps,
    search_index,
    index_timestamps,
    index_paths,
    top_k=20,
    per_frame_k=5,
):
    if search_index.ntotal <= 0:
        return []
    if not isinstance(index_timestamps, (list, np.ndarray)) or not isinstance(index_paths, (list, np.ndarray)):
        return []

    actual_k = min(int(per_frame_k), int(search_index.ntotal))
    distances, indices = search_index.search(query_vectors, actual_k)

    candidates = []
    for source_index in range(len(source_timestamps)):
        for rank in range(actual_k):
            matched_index = int(indices[source_index][rank])
            if matched_index < 0 or matched_index >= len(index_paths) or matched_index >= len(index_timestamps):
                continue
            candidates.append(
                {
                    "source_time": float(source_timestamps[source_index]),
                    "match_time": float(index_timestamps[matched_index]),
                    "score": float(distances[source_index][rank]),
                    "video_path": str(index_paths[matched_index]),
                }
            )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    deduped = []
    visited = set()
    for item in candidates:
        key = (item["video_path"], round(item["match_time"], 2))
        if key in visited:
            continue
        visited.add(key)
        deduped.append(item)
        if len(deduped) >= int(top_k):
            break
    return deduped


def _emit(callback, percent, text):
    if callback:
        callback(int(percent), str(text))


def _load_yt_dlp():
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise RuntimeError("yt-dlp is not installed. Run: pip install yt-dlp") from exc
    return yt_dlp


def _normalize_link_input(raw_text):
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("Video link is required.")

    # Allow pasting mixed text like: "title ... https://example.com/..."
    match = re.search(r"(https?://[^\s]+)", text, flags=re.IGNORECASE)
    candidate = match.group(1) if match else text
    candidate = candidate.strip().strip("()[]{}<>\"'，。；！？")

    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate
    raise ValueError("Input does not contain a valid video URL.")
