"""Structured indexing progress payloads for UI formatting."""

from __future__ import annotations

import os
import threading
import time

PREFIX = "index_progress"


def build_progress_token(
    *,
    stage: str,
    video_name: str = "",
    file_index: int = 0,
    file_total: int = 0,
    done: int = 0,
    total: int = 0,
) -> str:
    name = os.path.basename(str(video_name or ""))
    return "|".join(
        [
            PREFIX,
            str(stage or "").strip().lower(),
            str(max(0, int(file_index))),
            str(max(0, int(file_total))),
            str(max(0, int(done))),
            str(max(0, int(total))),
            name,
        ]
    )


def parse_progress_token(text: str):
    raw = str(text or "").strip()
    if not raw.startswith(f"{PREFIX}|"):
        return None
    parts = raw.split("|")
    if len(parts) < 7:
        return None
    return {
        "stage": parts[1],
        "file_index": int(parts[2]) if parts[2].isdigit() else 0,
        "file_total": int(parts[3]) if parts[3].isdigit() else 0,
        "done": int(parts[4]) if parts[4].isdigit() else 0,
        "total": int(parts[5]) if parts[5].isdigit() else 0,
        "video_name": parts[6],
    }


def format_progress_text(text: str, texts: dict) -> str:
    payload = parse_progress_token(text)
    if not payload:
        return text

    stage = payload["stage"]
    name = payload["video_name"] or texts.get("index_progress_unknown_video", "video")
    done = payload["done"]
    total = payload["total"]
    file_index = payload["file_index"]
    file_total = payload["file_total"]

    if stage == "file":
        if file_total > 0:
            return texts.get("index_progress_file", "{name} ({current}/{total})").format(
                name=name,
                current=file_index,
                total=file_total,
            )
        return texts.get("index_progress_file_open", "{name}").format(name=name)

    if stage == "scan":
        if file_total > 0:
            return texts.get("index_progress_scan", "Syncing videos {current}/{total}").format(
                current=file_index,
                total=file_total,
            )
        return texts.get("index_progress_scan_open", "Syncing videos…")

    count_suffix = ""
    if total > 0:
        count_suffix = f"{done}/{total}"
    elif done > 0:
        count_suffix = str(done)

    if stage == "decode":
        key = "index_progress_decode" if total > 0 else "index_progress_decode_open"
        return texts.get(key, "{name}: frames {count}").format(name=name, count=count_suffix or done)
    if stage == "encode":
        key = "index_progress_encode" if total > 0 else "index_progress_encode_open"
        return texts.get(key, "{name}: embedding {count}").format(name=name, count=count_suffix or done)
    if stage == "chunk":
        return texts.get("index_progress_chunk", "{name}: building segments").format(name=name)
    if stage == "save":
        return texts.get("index_progress_save", "{name}: saving index").format(name=name)
    if stage == "global":
        return texts.get("index_progress_global", "Building global search index…")
    if stage == "reuse":
        return texts.get("index_progress_reuse", "{name}: reusing cached vectors").format(name=name)
    if stage == "lance_index":
        if total > 0:
            return texts.get(
                "index_progress_lance_index",
                "Optimizing vector search index ({count} vectors)",
            ).format(count=total)
        return texts.get("index_progress_lance_index_open", "Optimizing vector search index…")
    if stage == "rebuild_index":
        if file_total > 0:
            return texts.get("index_progress_rebuild_index", "{current}/{total}: rebuilding index from vectors").format(
                current=file_index,
                total=file_total,
            )
        return texts.get("index_progress_rebuild_index_open", "Rebuilding index from cached vectors…")
    if stage == "upgrade_index":
        if file_total > 0:
            return texts.get("index_progress_upgrade_index", "{current}/{total}: upgrading search index").format(
                current=file_index,
                total=file_total,
            )
        return texts.get("index_progress_upgrade_index_open", "Upgrading search index…")

    return text


def compute_overall_percent(file_index, file_total, stage_done, stage_total, *, cap=94):
    """Map file index + within-file progress into 0–cap percent for the bar."""
    file_total = max(1, int(file_total or 1))
    file_index = max(1, min(int(file_index or 1), file_total))
    file_span = float(cap) / float(file_total)
    file_base = (file_index - 1) * file_span
    if stage_total > 0:
        file_base += file_span * (float(stage_done) / float(stage_total))
    return int(max(0, min(cap, round(file_base))))


class IndexingProgressReporter:
    """Throttle per-video progress emissions (safe to call from reader + encode threads)."""

    def __init__(
        self,
        callback,
        *,
        video_name: str,
        file_index: int = 1,
        file_total: int = 1,
        min_interval_sec: float = 0.25,
    ):
        self._callback = callback
        self._video_name = video_name
        self._file_index = max(1, int(file_index or 1))
        self._file_total = max(1, int(file_total or 1))
        self._min_interval = max(0.05, float(min_interval_sec))
        self._last_emit = 0.0
        self._last_stage = ""
        self._lock = threading.Lock()

    def emit(
        self,
        stage: str,
        done: int = 0,
        total: int = 0,
        *,
        force: bool = False,
        percent_cap: int = 94,
    ):
        if not callable(self._callback):
            return
        stage = str(stage or "").strip().lower()
        done = max(0, int(done))
        total = max(0, int(total))
        with self._lock:
            now = time.monotonic()
            if (
                not force
                and stage == self._last_stage
                and now - self._last_emit < self._min_interval
                and done < total
                and done > 1
            ):
                return
            self._last_emit = now
            self._last_stage = stage
            token = build_progress_token(
                stage=stage,
                video_name=self._video_name,
                file_index=self._file_index,
                file_total=self._file_total,
                done=done,
                total=total,
            )
            percent = compute_overall_percent(
                self._file_index,
                self._file_total,
                done,
                total,
                cap=percent_cap,
            )
        self._callback(percent, token)
