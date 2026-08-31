"""Cluster CAM++ embeddings onto empty dialogue speaker cells."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import numpy as np

from src.app.logging_utils import get_logger
from src.core.asr.campplus_onnx import DEFAULT_SAMPLE_RATE, get_campplus_engine
from src.storage.dialogue_transcript_store import (
    is_auto_speaker_label,
    load_dialogue_transcript,
    normalize_dialogue_speaker,
    update_dialogue_segment_speakers,
)

logger = get_logger("speaker_cluster")

# VAD/ASR rows are speech regions, not speaker turns. Embed the loudest ~2s
# inside each cue (CAM++ wants a short utterance). Cluster with average
# linkage so A~B and B~C do not force A=C, unlike union-find / single linkage.
MIN_EMBED_SEC = 0.4
WINDOW_SEC = 2.0
HOP_SEC = 0.75
MAX_WINDOWS_PER_CUE = 1
MIN_WINDOW_RMS = 5.0e-4
COSINE_THRESHOLD = 0.50
ABSORB_MAX_SIZE = 2
ABSORB_MIN_TARGET_SIZE = 3
ABSORB_SIM = 0.40
ProgressCallback = Callable[[float, str], None]


def speaker_cluster_label(index: int) -> str:
    return f"声线{max(1, int(index) + 1)}"


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    rows = np.asarray(matrix, dtype=np.float32)
    if rows.ndim == 1:
        rows = rows.reshape(1, -1)
    norms = np.linalg.norm(rows, axis=1, keepdims=True)
    norms = np.maximum(norms, 1.0e-8)
    return rows / norms


def _rms(wave: np.ndarray) -> float:
    samples = np.asarray(wave, dtype=np.float32).reshape(-1)
    if samples.size <= 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples))))


def _overlap_ratio(left: int, left_end: int, right: int, right_end: int) -> float:
    span = max(1, min(left_end - left, right_end - right))
    overlap = max(0, min(left_end, right_end) - max(left, right))
    return float(overlap) / float(span)


def embed_windows_for_span(
    waveform: np.ndarray,
    *,
    start_sec: float,
    end_sec: float,
    sample_rate: int,
    max_windows: int | None = None,
) -> list[tuple[np.ndarray, float]]:
    """Loudest non-overlapping CAM++ windows inside one ASR cue."""
    sr = max(1, int(sample_rate))
    audio = np.asarray(waveform, dtype=np.float32).reshape(-1)
    start = max(0, int(round(float(start_sec) * sr)))
    end = min(int(audio.shape[0]), int(round(float(end_sec) * sr)))
    min_samples = int(round(MIN_EMBED_SEC * sr))
    if end - start < min_samples:
        return []
    span = audio[start:end]
    win = int(round(WINDOW_SEC * sr))
    hop = max(min_samples, int(round(HOP_SEC * sr)))
    if span.size <= win:
        energy = _rms(span)
        if energy < MIN_WINDOW_RMS:
            return []
        return [(span, energy)]

    candidates: list[tuple[np.ndarray, float, int]] = []
    pos = 0
    while pos + min_samples <= span.size:
        piece = span[pos : min(span.size, pos + win)]
        if piece.size >= min_samples:
            energy = _rms(piece)
            if energy >= MIN_WINDOW_RMS:
                candidates.append((piece, energy, pos))
        if pos + win >= span.size:
            break
        pos += hop
    candidates.sort(key=lambda item: -item[1])
    if candidates:
        peak = float(candidates[0][1])
        floor = max(MIN_WINDOW_RMS, 0.25 * peak)
        candidates = [item for item in candidates if float(item[1]) >= floor]
    picked: list[tuple[np.ndarray, float, int]] = []
    for piece, energy, pos in candidates:
        piece_end = pos + int(piece.size)
        if any(
            _overlap_ratio(pos, piece_end, other_pos, other_pos + int(other.size)) > 0.45
            for other, _other_energy, other_pos in picked
        ):
            continue
        picked.append((piece, energy, pos))
        if len(picked) >= max(1, int(MAX_WINDOWS_PER_CUE if max_windows is None else max_windows)):
            break
    return [(piece, energy) for piece, energy, _pos in picked]


def _remap_labels_by_size(raw: list[int]) -> list[int]:
    counts: dict[int, int] = {}
    for label in raw:
        counts[label] = counts.get(label, 0) + 1
    ranked = sorted(counts, key=lambda label: (-counts[label], label))
    mapping = {old: index for index, old in enumerate(ranked)}
    return [mapping[label] for label in raw]


def _absorb_tiny_clusters(
    embeddings: np.ndarray,
    labels: list[int],
    *,
    max_size: int = ABSORB_MAX_SIZE,
    min_target: int = ABSORB_MIN_TARGET_SIZE,
    sim: float = ABSORB_SIM,
) -> list[int]:
    """Fold 1–2 shot clusters into the nearest larger voice when they still match."""
    embs = l2_normalize(embeddings)
    raw = list(labels)
    cutoff = float(sim)
    for _ in range(max(1, len(set(raw)))):
        groups: dict[int, list[int]] = {}
        for index, label in enumerate(raw):
            groups.setdefault(int(label), []).append(index)
        tiny = [label for label, members in groups.items() if len(members) <= int(max_size)]
        big = [label for label, members in groups.items() if len(members) >= int(min_target)]
        if not tiny or not big:
            break
        centroids = {
            label: l2_normalize(embs[members].mean(axis=0, keepdims=True))[0]
            for label, members in groups.items()
        }
        big_mat = np.stack([centroids[label] for label in big], axis=0)
        moved = False
        for label in tiny:
            scores = big_mat @ centroids[label]
            best = int(np.argmax(scores))
            if float(scores[best]) < cutoff:
                continue
            target = big[best]
            for index in groups[label]:
                raw[index] = target
            moved = True
        if not moved:
            break
    return raw


def cluster_embeddings(
    embeddings: np.ndarray,
    *,
    threshold: float = COSINE_THRESHOLD,
    seed_order: list[int] | None = None,
    absorb_tiny: bool = True,
) -> list[int]:
    """Average-linkage clusters while mean pairwise cosine >= ``threshold``.

    ``seed_order`` is accepted for compatibility and ignored: linkage is global.
    """
    del seed_order
    embs = l2_normalize(embeddings)
    count = int(embs.shape[0])
    if count <= 0:
        return []
    if count == 1:
        return [0]
    sims = np.clip(embs @ embs.T, -1.0, 1.0).astype(np.float64, copy=False)
    np.fill_diagonal(sims, -np.inf)
    sizes = np.ones(count, dtype=np.float64)
    labels = np.arange(count, dtype=np.int32)
    cutoff = float(threshold)
    for _ in range(count - 1):
        flat = int(np.argmax(sims))
        left, right = divmod(flat, count)
        best = float(sims[left, right])
        if left == right or not np.isfinite(best) or best < cutoff:
            break
        if right < left:
            left, right = right, left
        weight_left = float(sizes[left])
        weight_right = float(sizes[right])
        merged = (weight_left * sims[left] + weight_right * sims[right]) / (weight_left + weight_right)
        sims[left, :] = merged
        sims[:, left] = merged
        sims[left, left] = -np.inf
        sims[right, :] = -np.inf
        sims[:, right] = -np.inf
        sizes[left] = weight_left + weight_right
        labels[labels == right] = left
    raw = [int(label) for label in labels]
    if absorb_tiny:
        raw = _absorb_tiny_clusters(embs, raw)
    return _remap_labels_by_size(raw)


def _resolve_cluster_media_path(
    video_id: str,
    *,
    preferred: str = "",
    stored: str = "",
    config=None,
) -> tuple[str, str]:
    for candidate in (preferred, stored):
        path = os.path.normpath(str(candidate or "").strip())
        if path and os.path.isfile(path):
            return path, ""
    try:
        from src.services.understanding_service import resolve_video_context

        context = resolve_video_context(video_id, config=config, probe_duration=False)
        path = os.path.normpath(str(context.get("video_path") or "").strip())
        if path and (context.get("source_exists") or os.path.isfile(path)):
            return path, str(context.get("library_path") or "")
    except Exception as exc:
        logger.warning("Could not resolve current media path for %s: %s", video_id, exc)
    return "", ""


def cluster_video_speakers(
    video_id: str,
    *,
    video_path: str = "",
    config=None,
    waveform: np.ndarray | None = None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    embed_fn: Callable[[np.ndarray], np.ndarray] | None = None,
    progress_callback: ProgressCallback | None = None,
    stop_callback: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Fill empty / auto speaker labels from CAM++ clusters. Manual names stay."""
    from src.core.understanding.base import UnderstandingStoppedError
    from src.services.asr_index_service import is_hardsub_ocr_source

    vid = str(video_id or "").strip()
    if not vid:
        return {"ok": False, "error": "missing video_id", "labeled": 0, "skipped": 0, "speakers": 0}

    def _stopped() -> bool:
        return bool(stop_callback and stop_callback())

    def _progress(value: float, stage: str) -> None:
        if progress_callback:
            progress_callback(float(value), stage)

    payload = load_dialogue_transcript(vid, config=config) or {}
    default_source = str(payload.get("asr_source") or "").strip()
    segments = list(payload.get("segments") or [])
    candidates: list[dict[str, Any]] = []
    skipped_manual = 0
    for index, row in enumerate(segments):
        if not isinstance(row, dict):
            continue
        source = str(row.get("asr_source") or default_source or "").strip()
        if not source or is_hardsub_ocr_source(source):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            seg_index = int(row.get("seg_index", index))
        except (TypeError, ValueError):
            seg_index = index
        start = float(row.get("start") or 0.0)
        end = float(row.get("end") or start)
        speaker = normalize_dialogue_speaker(row.get("speaker"))
        if speaker and not is_auto_speaker_label(speaker):
            skipped_manual += 1
            continue
        if (end - start) < MIN_EMBED_SEC:
            continue
        candidates.append(
            {
                "seg_index": seg_index,
                "start": start,
                "end": end,
            }
        )
    if not candidates:
        return {
            "ok": True,
            "labeled": 0,
            "skipped": skipped_manual,
            "speakers": 0,
            "video_id": vid,
        }

    if _stopped():
        raise UnderstandingStoppedError("stopped")

    audio = waveform
    sr = int(sample_rate)
    if audio is None:
        media, library_path = _resolve_cluster_media_path(
            vid,
            preferred=video_path,
            stored=str(payload.get("video_path") or ""),
            config=config,
        )
        if not media:
            return {
                "ok": False,
                "error": "missing video_path",
                "labeled": 0,
                "skipped": skipped_manual,
                "speakers": 0,
            }
        stored = str(payload.get("video_path") or "").strip()
        if os.path.normcase(os.path.normpath(stored)) != os.path.normcase(media):
            from src.storage.dialogue_transcript_store import update_dialogue_transcript_location

            update_dialogue_transcript_location(
                vid,
                video_path=media,
                library_path=library_path or str(payload.get("library_path") or ""),
                config=config,
            )
        _progress(0.05, "extract_audio")
        from src.core.asr.audio_extract import extract_audio_mono_f32

        audio = extract_audio_mono_f32(media, sample_rate=sr, progress_callback=progress_callback)
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)

    embed = embed_fn
    if embed is None:
        engine = get_campplus_engine()
        embed = lambda wav, _engine=engine: _engine.embed_waveform(wav, sample_rate=sr)

    window_vectors: list[np.ndarray] = []
    window_energy: list[float] = []
    window_cues: list[int] = []
    usable: list[dict[str, Any]] = []
    total = len(candidates)
    for index, item in enumerate(candidates):
        if _stopped():
            raise UnderstandingStoppedError("stopped")
        windows = embed_windows_for_span(
            audio,
            start_sec=item["start"],
            end_sec=item["end"],
            sample_rate=sr,
        )
        _progress(0.1 + 0.8 * ((index + 1) / max(1, total)), f"embed:{index + 1}:{total}")
        if not windows:
            continue
        cue_index = len(usable)
        embedded_any = False
        for clip, energy in windows:
            try:
                vector = np.asarray(embed(clip), dtype=np.float32).reshape(-1)
            except Exception as exc:
                logger.warning("CAM++ embed failed for seg %s: %s", item["seg_index"], exc)
                continue
            if vector.size <= 0:
                continue
            window_vectors.append(vector)
            window_energy.append(float(energy))
            window_cues.append(cue_index)
            embedded_any = True
        if embedded_any:
            usable.append(item)

    if len(usable) < 1 or not window_vectors:
        return {
            "ok": True,
            "labeled": 0,
            "skipped": skipped_manual,
            "speakers": 0,
            "video_id": vid,
        }

    seed_order = sorted(range(len(window_vectors)), key=lambda index: -window_energy[index])
    window_labels = cluster_embeddings(
        np.stack(window_vectors, axis=0),
        seed_order=seed_order,
    )
    best: list[tuple[float, int] | None] = [None] * len(usable)
    for cue_index, label, energy in zip(window_cues, window_labels, window_energy):
        current = best[cue_index]
        if current is None or float(energy) > current[0] or (
            float(energy) == current[0] and int(label) < current[1]
        ):
            best[cue_index] = (float(energy), int(label))
    assignments = {}
    for item, picked in zip(usable, best):
        if picked is None:
            continue
        assignments[int(item["seg_index"])] = speaker_cluster_label(picked[1])
    updated = update_dialogue_segment_speakers(vid, assignments, config=config)
    speaker_count = len({label for label in assignments.values()})
    _progress(1.0, "done")
    return {
        "ok": True,
        "labeled": int(updated),
        "skipped": skipped_manual,
        "speakers": speaker_count,
        "video_id": vid,
    }
