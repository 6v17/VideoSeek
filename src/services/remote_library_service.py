import os
import json
import time
import shutil
import subprocess
import zipfile
from typing import Callable

import cv2
import numpy as np

from src.app.config import get_data_storage_paths, load_config
from src.core.clip_embedding import get_clip_embeddings_batch
from src.core.faiss_index import create_clip_index
from src.services.remote_link_precheck_service import (
    build_existing_source_candidates as _build_existing_source_candidates,
    build_precheck_source_candidates as _build_precheck_source_candidates,
    build_stable_source_id as _build_stable_source_id,
    normalize_link_input as _normalize_link_input,
)
from src.utils import get_ffmpeg_path, resolve_sampling_fps

ProgressCallback = Callable[[int, str], None]


def get_remote_library_paths():
    config = load_config()
    return {
        "index_file": config.get("remote_index_file", ""),
        "vector_file": config.get("remote_vector_file", ""),
    }


def get_remote_library_status():
    paths = get_remote_library_paths()
    return {
        "ready": bool(
            paths["index_file"]
            and paths["vector_file"]
            and os.path.exists(paths["index_file"])
            and os.path.exists(paths["vector_file"])
        ),
        "index_file": paths["index_file"],
        "vector_file": paths["vector_file"],
    }


def list_remote_link_details():
    status = get_remote_library_status()
    vector_file = status["vector_file"]
    if not vector_file or not os.path.exists(vector_file):
        return {
            "ready": status["ready"],
            "index_file": status["index_file"],
            "vector_file": vector_file,
            "entries": [],
            "total_links": 0,
            "total_vectors": 0,
        }

    payload = _load_existing_payload(vector_file)
    source_links = payload.get("source_links", [])
    titles = payload.get("titles", [])
    source_ids = payload.get("paths", [])
    timestamps = payload.get("timestamps", [])
    size = min(len(source_links), len(titles), len(source_ids), len(timestamps))
    grouped = {}

    for idx in range(size):
        source_link = str(source_links[idx] or "").strip()
        source_id = str(source_ids[idx] or "").strip()
        key = source_link or source_id
        if not key:
            key = "unknown"
        timestamp = float(timestamps[idx])
        item = grouped.get(key)
        if not item:
            item = {
                "source_link": source_link,
                "title": str(titles[idx] or source_link or source_id or ""),
                "source_id": source_id,
                "frames": 0,
                "min_time": timestamp,
                "max_time": timestamp,
            }
            grouped[key] = item
        item["frames"] += 1
        item["min_time"] = min(item["min_time"], timestamp)
        item["max_time"] = max(item["max_time"], timestamp)

    entries = list(grouped.values())
    entries.sort(key=lambda item: (-int(item["frames"]), item["source_link"] or item["source_id"]))
    return {
        "ready": status["ready"],
        "index_file": status["index_file"],
        "vector_file": vector_file,
        "entries": entries,
        "total_links": len(entries),
        "total_vectors": size,
    }


def build_remote_library_from_links(
    links,
    mode="download",
    incremental=True,
    fps=0,
    max_frames_per_video=None,
    progress_callback=None,
):
    started_at = time.time()
    normalized_links = []
    seen = set()
    for item in links or []:
        candidate = _normalize_link_input(str(item))
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized_links.append(candidate)
    links = normalized_links
    if not links:
        raise RuntimeError("No valid video URLs found in input.")

    config = load_config()
    sampled_fps = float(fps) if float(fps) > 0 else float(config.get("fps", 1.0))
    if max_frames_per_video is None:
        max_frames_per_video = int(config.get("remote_max_frames", 2000))
    max_frames_per_video = max(50, int(max_frames_per_video))
    paths = get_remote_library_paths()
    index_file = paths["index_file"]
    vector_file = paths["vector_file"]
    if not index_file or not vector_file:
        raise RuntimeError("Remote library file paths are not configured.")

    os.makedirs(os.path.dirname(index_file), exist_ok=True)
    os.makedirs(os.path.dirname(vector_file), exist_ok=True)

    all_vectors = []
    all_timestamps = []
    all_paths = []
    all_source_links = []
    all_titles = []
    existing_keys = set()
    existing_source_ids = set()

    if incremental and os.path.exists(vector_file):
        existing = _load_existing_payload(vector_file)
        if existing["vector"].size > 0:
            all_vectors.append(existing["vector"].astype("float32"))
            all_timestamps.extend(existing["timestamps"])
            all_paths.extend(existing["paths"])
            all_source_links.extend(existing["source_links"])
            all_titles.extend(existing["titles"])
            existing_keys = _build_existing_keys(existing["paths"], existing["timestamps"])
            existing_source_ids = _build_existing_source_candidates(existing["paths"], existing["source_links"])

    new_vectors_count = 0
    success_links = []
    skipped_links = []
    failed_links = []
    total_links = len(links)
    for idx, link in enumerate(links, start=1):
        base = int(((idx - 1) / max(1, total_links)) * 90)
        step_span = max(1, int(90 / max(1, total_links)))
        _emit(progress_callback, base, f"Preparing source {idx}/{total_links}")
        pre_candidates = _build_precheck_source_candidates(link)
        if any(candidate in existing_source_ids for candidate in pre_candidates):
            skipped_links.append({"link": link, "reason": "duplicate_source"})
            _emit(progress_callback, min(95, base + 8), f"Skipped source {idx}/{total_links}")
            continue

        try:
            _emit(progress_callback, min(95, base + max(1, int(step_span * 0.12))), f"Resolving source {idx}/{total_links}")
            source = _prepare_source(link, mode=mode)
            if str(source.get("source_id", "")).strip():
                existing_source_ids.add(str(source["source_id"]).strip())
            duration = _probe_duration(source["input"], headers=source.get("http_headers"))
            effective_fps = resolve_sampling_fps(duration, config=config, requested_fps=sampled_fps)
            if duration and duration > 0 and (effective_fps * duration) > max_frames_per_video:
                effective_fps = min(effective_fps, max(float(max_frames_per_video) / float(duration), 0.01))
            _emit(progress_callback, min(95, base + max(1, int(step_span * 0.35))), f"Extracting frames {idx}/{total_links}")
            frames, timestamps = _extract_frames(
                source["input"],
                fps=effective_fps,
                max_frames=max_frames_per_video,
                headers=source.get("http_headers"),
            )
            if not frames:
                skipped_links.append({"link": link, "reason": "no_frames"})
                continue
            _emit(progress_callback, min(95, base + max(1, int(step_span * 0.62))), f"Embedding frames {idx}/{total_links}")
            vectors = get_clip_embeddings_batch(frames).astype("float32")
            if vectors.size == 0:
                skipped_links.append({"link": link, "reason": "no_embeddings"})
                continue

            source_id = str(source.get("source_id", "") or source.get("source_link", ""))
            _emit(progress_callback, min(95, base + max(1, int(step_span * 0.78))), f"Merging vectors {idx}/{total_links}")
            filtered_indices = []
            filtered_timestamps = []
            for local_idx, ts in enumerate(timestamps):
                key = _compose_key(source_id, ts)
                if key in existing_keys:
                    continue
                existing_keys.add(key)
                filtered_indices.append(local_idx)
                filtered_timestamps.append(float(ts))

            if not filtered_indices:
                skipped_links.append({"link": link, "reason": "duplicate"})
                continue

            filtered_vectors = vectors[filtered_indices]
            new_vectors_count += int(filtered_vectors.shape[0])
            all_vectors.append(filtered_vectors)
            all_timestamps.extend(filtered_timestamps)
            all_paths.extend([source_id] * len(filtered_indices))
            all_source_links.extend([source["source_link"]] * len(filtered_indices))
            all_titles.extend([source.get("title", source["source_link"])] * len(filtered_indices))

            _emit(
                progress_callback,
                min(95, base + max(1, int(step_span * 0.92))),
                f"Indexed {len(filtered_indices)} frames from source {idx}/{total_links}",
            )
            success_links.append({"link": link, "indexed_frames": int(len(filtered_indices))})
        except Exception as exc:
            failed_links.append({"link": link, "error": str(exc)})
            _emit(progress_callback, min(95, base + 8), f"Skipped source {idx}/{total_links}")
            continue

    if not all_vectors:
        raise RuntimeError("No vectors available after processing links.")

    _emit(progress_callback, 96, "Building FAISS index")
    merged_vectors = np.vstack(all_vectors).astype("float32")
    create_clip_index(merged_vectors, index_file)

    payload = {
        "vector": merged_vectors,
        "timestamps": np.asarray(all_timestamps, dtype="float32"),
        "paths": np.asarray(all_paths, dtype=object),
        "source_links": np.asarray(all_source_links, dtype=object),
        "titles": np.asarray(all_titles, dtype=object),
    }
    np.save(vector_file, payload)
    _emit(progress_callback, 100, "Remote library build completed")

    status = get_remote_library_status()
    status["new_vectors"] = int(new_vectors_count)
    status["total_vectors"] = int(merged_vectors.shape[0])
    status["failed_links"] = failed_links
    status["success_links"] = success_links
    status["skipped_links"] = skipped_links
    status["success_count"] = len(success_links)
    status["skipped_count"] = len(skipped_links)
    status["failed_count"] = len(failed_links)
    status["duration_sec"] = round(max(0.0, time.time() - started_at), 3)
    status["report_path"] = _write_build_report(
        mode=mode,
        requested_links=links,
        status=status,
        max_frames_per_video=max_frames_per_video,
        sampled_fps=sampled_fps,
    )
    return status


def export_remote_library_zip(zip_path):
    status = get_remote_library_status()
    if not status["ready"]:
        raise RuntimeError("Remote library is not ready.")

    os.makedirs(os.path.dirname(zip_path), exist_ok=True) if os.path.dirname(zip_path) else None
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(status["index_file"], arcname="remote_index.faiss")
        archive.write(status["vector_file"], arcname="remote_vectors.npy")
    return zip_path


def import_remote_library_zip(zip_path):
    if not os.path.exists(zip_path):
        raise RuntimeError("Zip file does not exist.")
    paths = get_remote_library_paths()
    index_file = paths["index_file"]
    vector_file = paths["vector_file"]
    if not index_file or not vector_file:
        raise RuntimeError("Remote library file paths are not configured.")

    os.makedirs(os.path.dirname(index_file), exist_ok=True)
    os.makedirs(os.path.dirname(vector_file), exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        entries = set(archive.namelist())
        if "remote_index.faiss" not in entries or "remote_vectors.npy" not in entries:
            raise RuntimeError("Invalid package: missing remote_index.faiss or remote_vectors.npy")
        with archive.open("remote_index.faiss", "r") as source, open(index_file, "wb") as target:
            target.write(source.read())
        with archive.open("remote_vectors.npy", "r") as source, open(vector_file, "wb") as target:
            target.write(source.read())
    return get_remote_library_status()

def _prepare_source(link, mode="download"):
    yt_dlp = _load_yt_dlp()
    if mode == "download":
        cache_dir = get_data_storage_paths().get("remote_build_cache_dir", "")
        if not cache_dir:
            raise RuntimeError("Remote build cache path is not configured.")
        os.makedirs(cache_dir, exist_ok=True)
        options = {
            "format": "mp4/bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 10,
            "retries": 1,
            "extractor_retries": 1,
            "outtmpl": os.path.join(cache_dir, "%(id)s_%(title).80s.%(ext)s"),
            "restrictfilenames": True,
        }
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(link, download=True)
            output_path = _resolve_downloaded_file(info, downloader)
        if not output_path or not os.path.exists(output_path):
            raise RuntimeError(f"Download failed: {link}")
        source_link = info.get("webpage_url") or link
        return {
            "input": output_path,
            "source_link": source_link,
            "title": info.get("title") or link,
            "source_id": _build_stable_source_id(info.get("id"), source_link, output_path),
            "http_headers": {},
        }

    options = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 10,
        "retries": 1,
        "extractor_retries": 1,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(link, download=False)
    stream_url = info.get("url") or ""
    stream_headers = dict(info.get("http_headers") or {})
    if not stream_url:
        preferred = None
        fallback = None
        for fmt in info.get("formats") or []:
            candidate_url = fmt.get("url") or ""
            if not candidate_url:
                continue
            if fallback is None:
                fallback = fmt
            if str(fmt.get("vcodec", "none")) != "none":
                preferred = fmt
                break
        chosen = preferred or fallback
        if chosen:
            stream_url = chosen.get("url") or ""
            stream_headers = dict(chosen.get("http_headers") or stream_headers)
    if not stream_url:
        raise RuntimeError(f"Stream URL not found: {link}")
    source_link = info.get("webpage_url") or link
    return {
        "input": stream_url,
        "source_link": source_link,
        "title": info.get("title") or link,
        "source_id": _build_stable_source_id(info.get("id"), source_link, stream_url),
        "http_headers": stream_headers,
    }


def _resolve_downloaded_file(info, downloader):
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


def _extract_frames(source_input, fps=1, max_frames=300, headers=None):
    ffmpeg_bin = get_ffmpeg_path()
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-rw_timeout",
        "10000000",
    ]
    header_blob = _build_ffmpeg_headers(headers or {})
    if header_blob:
        command.extend(["-headers", header_blob])
    command.extend([
        "-i",
        source_input,
        "-vf",
        f"fps={max(0.01, float(fps)):.6f},scale=224:224",
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
    ])

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
    safe_fps = max(0.01, float(fps))
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


def _load_yt_dlp():
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise RuntimeError("yt-dlp is not installed. Run: pip install yt-dlp") from exc
    return yt_dlp


def _load_existing_payload(path):
    data = np.load(path, allow_pickle=True).item()
    return {
        "vector": np.asarray(data.get("vector", np.empty((0, 0), dtype=np.float32)), dtype=np.float32),
        "timestamps": [float(value) for value in data.get("timestamps", [])],
        "paths": [str(value) for value in data.get("paths", [])],
        "source_links": [str(value) for value in data.get("source_links", [])],
        "titles": [str(value) for value in data.get("titles", [])],
    }


def _build_existing_keys(paths, timestamps):
    keys = set()
    count = min(len(paths), len(timestamps))
    for idx in range(count):
        keys.add(_compose_key(paths[idx], timestamps[idx]))
    return keys


def _compose_key(source_id, timestamp):
    return f"{source_id}::{int(round(float(timestamp) * 1000))}"


def _emit(callback, value, text):
    if callback:
        callback(int(value), str(text))


def _build_ffmpeg_headers(headers):
    if not isinstance(headers, dict) or not headers:
        return ""
    lines = []
    for key, value in headers.items():
        k = str(key).strip()
        v = str(value).strip()
        if not k or not v:
            continue
        lines.append(f"{k}: {v}")
    if not lines:
        return ""
    return "\r\n".join(lines) + "\r\n"


def _probe_duration(source_input, headers=None):
    ffprobe_bin = _get_ffprobe_path()
    if not ffprobe_bin:
        return _probe_local_duration_fallback(source_input)

    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
    ]
    header_blob = _build_ffmpeg_headers(headers or {})
    if header_blob:
        command.extend(["-headers", header_blob])
    command.append(source_input)

    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            startupinfo=startupinfo,
            timeout=10,
        )
        if result.returncode != 0:
            return _probe_local_duration_fallback(source_input)
        text = (result.stdout or "").strip()
        if not text:
            return _probe_local_duration_fallback(source_input)
        duration = float(text)
        if duration <= 0:
            return _probe_local_duration_fallback(source_input)
        return duration
    except Exception:
        return _probe_local_duration_fallback(source_input)


def _get_ffprobe_path():
    ffmpeg_bin = get_ffmpeg_path()
    ffmpeg_dir = os.path.dirname(ffmpeg_bin)
    ffmpeg_name = os.path.basename(ffmpeg_bin).lower()
    if ffmpeg_name.startswith("ffmpeg"):
        candidate_name = ffmpeg_name.replace("ffmpeg", "ffprobe", 1)
        candidate = os.path.join(ffmpeg_dir, candidate_name)
        if os.path.exists(candidate):
            return candidate
    from_path = shutil.which("ffprobe")
    return from_path or ""


def _probe_local_duration_fallback(source_input):
    # Fallback for local files when ffprobe is unavailable.
    if not source_input or str(source_input).startswith(("http://", "https://")):
        return None
    try:
        cap = cv2.VideoCapture(str(source_input))
        if not cap.isOpened():
            return None
        frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        cap.release()
        if frame_count > 0 and fps > 0:
            duration = frame_count / fps
            if duration > 0:
                return duration
    except Exception:
        return None
    return None


def _write_build_report(mode, requested_links, status, max_frames_per_video, sampled_fps):
    storage_paths = get_data_storage_paths()
    paths = get_remote_library_paths()
    vector_file = str(paths.get("vector_file", "") or "")
    report_path = str(storage_paths.get("remote_build_report_file", "") or "")
    if not report_path:
        report_dir = os.path.dirname(vector_file) if vector_file else ""
        if not report_dir:
            raise RuntimeError("Remote build report path is not configured.")
        report_path = os.path.join(report_dir, "build_report.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    payload = {
        "mode": str(mode),
        "sampled_fps": float(sampled_fps),
        "max_frames_per_video": int(max_frames_per_video),
        "requested_count": len(list(requested_links or [])),
        "duration_sec": float(status.get("duration_sec", 0.0)),
        "new_vectors": int(status.get("new_vectors", 0)),
        "total_vectors": int(status.get("total_vectors", 0)),
        "success_count": int(status.get("success_count", 0)),
        "failed_count": int(status.get("failed_count", 0)),
        "skipped_count": int(status.get("skipped_count", 0)),
        "success_links": list(status.get("success_links", [])),
        "failed_links": list(status.get("failed_links", [])),
        "skipped_links": list(status.get("skipped_links", [])),
        "index_file": str(paths.get("index_file", "") or ""),
        "vector_file": vector_file,
    }

    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return report_path


