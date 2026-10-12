"""Recap sidecar JSON paths, load, and write helpers.

``recap_service`` re-exports these names. Plan-edit / clip-VO rewrite stay in the runner.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.media.fcpxml import atomic_write_text, write_cuts_json
from src.services.recap_constants import RECAP_START_PLAN, TTS_SPEED


class RecapSidecarCorruptError(RuntimeError):
    """Primary sidecar exists but JSON is unreadable or the wrong shape.

    Callers must not treat this as "no plan" and regenerate over the file.
    """

    def __init__(self, path: Path | str, reason: str = ""):
        self.path = Path(path)
        detail = str(reason or "").strip()
        message = f"剧情规划文件已损坏，请从备份恢复或删除后重跑：{self.path}"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)


def recap_beats_path_for_video(video_path: str) -> Path:
    return _recap_sidecar_path(video_path, "_recap_beats.json")

def recap_cuts_path_for_video(video_path: str) -> Path:
    return _recap_sidecar_path(video_path, "_recap_cuts.json")

def _recap_sidecar_path(video_path: str, suffix: str) -> Path:
    video = Path(os.path.abspath(os.path.expanduser(str(video_path or "").strip())))
    return video.parent / f"{video.stem}{suffix}"

def _read_recap_sidecar(
    path: Path,
    required_key: str,
    *,
    raise_on_corrupt: bool = False,
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        if raise_on_corrupt:
            raise RecapSidecarCorruptError(path, str(exc)) from exc
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get(required_key), list):
        if raise_on_corrupt:
            raise RecapSidecarCorruptError(path, f"missing or invalid '{required_key}' list")
        return None
    if not payload.get(required_key):
        return None
    return payload

def _heal_recap_sidecar_to_primary(primary: Path, payload: Mapping[str, Any]) -> None:
    """Copy fallback payload onto the living primary path so later writes stay in sync."""
    try:
        atomic_write_text(
            primary,
            json.dumps(dict(payload), ensure_ascii=False, indent=2),
        )
    except OSError:
        pass

def _load_recap_sidecar(
    video_path: str,
    *,
    suffix: str,
    required_key: str,
    video_id: str = "",
) -> dict[str, Any] | None:
    primary = _recap_sidecar_path(video_path, suffix)
    # Corrupt primary must not look like "missing" (would regenerate and overwrite).
    payload = _read_recap_sidecar(primary, required_key, raise_on_corrupt=True)
    if payload is not None:
        return payload
    if primary.is_file():
        # Readable but empty/unusable — do not silently adopt a sibling stem.
        return None
    vid = str(video_id or "").strip()
    parent = Path(os.path.abspath(os.path.expanduser(str(video_path or "").strip()))).parent
    if not vid or not parent.is_dir():
        return None
    found: list[tuple[float, Path, dict[str, Any]]] = []
    for path in parent.glob(f"*{suffix}"):
        if path == primary:
            continue
        item = _read_recap_sidecar(path, required_key)
        if item is None or str(item.get("video_id") or "").strip() != vid:
            continue
        try:
            mtime = float(path.stat().st_mtime)
        except OSError:
            mtime = 0.0
        found.append((mtime, path, item))
    if not found:
        return None
    found.sort(key=lambda row: row[0], reverse=True)
    _mtime, _src, best = found[0]
    # Heal: read-from-A / write-to-B forks if we leave primary empty after rename.
    _heal_recap_sidecar_to_primary(primary, best)
    return best

def load_recap_beats(video_path: str, *, video_id: str = "") -> dict[str, Any] | None:
    return _load_recap_sidecar(
        video_path,
        suffix="_recap_beats.json",
        required_key="beats",
        video_id=video_id,
    )

def load_recap_cuts(video_path: str, *, video_id: str = "") -> dict[str, Any] | None:
    return _load_recap_sidecar(
        video_path,
        suffix="_recap_cuts.json",
        required_key="clips",
        video_id=video_id,
    )

def recap_beats_edited_by_user(payload: Mapping[str, Any] | None) -> bool:
    """True when the sidecar was last saved from the manual plan editor."""
    if not isinstance(payload, Mapping):
        return False
    return bool(payload.get("edited_by_user"))


def _backup_user_edited_beats(dest: Path) -> None:
    """Keep one ``*.bak`` snapshot before overwriting a user-edited plan."""
    if not dest.is_file():
        return
    try:
        previous = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    if not recap_beats_edited_by_user(previous):
        return
    bak = dest.with_name(f"{dest.name}.bak")
    try:
        atomic_write_text(bak, json.dumps(previous, ensure_ascii=False, indent=2))
    except OSError:
        pass


def write_recap_beats_file(
    dest: str | Path,
    *,
    title: str,
    video_id: str,
    allocated: list[Mapping[str, Any]],
    people: list[Mapping[str, Any]] | None = None,
    stage: str = RECAP_START_PLAN,
    edited_by_user: bool = False,
) -> Path:
    path = Path(dest)
    _backup_user_edited_beats(path)
    payload: dict[str, Any] = {
        "title": title,
        "video_id": video_id,
        "stage": stage,
        "target_sec": round(sum(float(item.get("budget_sec") or 0.0) for item in allocated), 1),
        "people": list(people or []),
        "beats": list(allocated),
    }
    if edited_by_user:
        payload["edited_by_user"] = True
    return atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )

def _recap_clip_records(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for clip in clips:
        row = {
            "name": clip.get("name"),
            "beat_id": clip.get("beat_id"),
            "chunk_index": clip.get("chunk_index"),
            "src_in": round(float(clip.get("src_in") or 0.0), 3),
            "src_out": round(float(clip.get("src_out") or 0.0), 3),
            "duration": round(
                float(clip.get("duration") or (float(clip.get("src_out") or 0.0) - float(clip.get("src_in") or 0.0))),
                3,
            ),
            "tl_in": round(float(clip.get("tl_in") or 0.0), 3),
            "tl_out": round(float(clip.get("tl_out") or 0.0), 3),
            "vo": clip.get("vo") or "",
            "vo_draft": str(clip.get("vo_draft") or clip.get("vo") or ""),
            "vo_tl_in": clip.get("vo_tl_in"),
            "vo_tl_out": clip.get("vo_tl_out"),
            "reason": str(clip.get("reason") or ""),
            "role": str(clip.get("role") or "").strip(),
        }
        match_status = str(clip.get("match_status") or "").strip()
        if match_status:
            row["match_status"] = match_status
        if clip.get("match_score") is not None:
            try:
                row["match_score"] = round(float(clip.get("match_score")), 3)
            except (TypeError, ValueError):
                pass
        if clip.get("match_threshold") is not None:
            try:
                row["match_threshold"] = round(float(clip.get("match_threshold")), 3)
            except (TypeError, ValueError):
                pass
        support = clip.get("evidence_support")
        if isinstance(support, Mapping):
            row["evidence_support"] = dict(support)
        for key in ("visual_score", "asr_score", "vlm_score", "character_score"):
            if clip.get(key) is None:
                continue
            try:
                row[key] = round(float(clip.get(key)), 3)
            except (TypeError, ValueError):
                pass
        rows.append(row)
    return rows

def write_recap_cuts_file(
    dest: str | Path,
    *,
    title: str,
    video_path: str,
    video_id: str,
    info: Mapping[str, Any],
    laid_out: Sequence[Mapping[str, Any]],
    beats_path: str | Path,
    stage: str,
) -> Path:
    clips = list(laid_out or [])
    return write_cuts_json(
        {
            "title": title,
            "video": video_path,
            "video_id": video_id,
            "stage": stage,
            "fps": info.get("fps"),
            "duration_sec": clips[-1]["tl_out"] if clips else 0,
            "tts_speed": TTS_SPEED,
            "clip_count": len(clips),
            "beats_path": str(beats_path),
            "clips": _recap_clip_records(clips),
        },
        dest,
    )

recap_clip_records = _recap_clip_records
