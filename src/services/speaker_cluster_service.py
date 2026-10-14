"""Cluster CAM++ embeddings onto empty dialogue speaker cells."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
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

# VAD/ASR rows are speech regions, not speaker turns. Take a few short CAM++
# windows per cue (not the whole span), then majority-vote the cue label.
# Manual names anchor clusters so unlabeled cues can inherit 店长 / 男主 etc.
# Prefer fewer 声线N over dozens of fragments users will never rename.
MIN_EMBED_SEC = 0.4
WINDOW_SEC = 2.0
HOP_SEC = 0.75
MAX_WINDOWS_PER_CUE = 3
MIN_WINDOW_RMS = 5.0e-4
COSINE_THRESHOLD = 0.50
ABSORB_MAX_SIZE = 4
ABSORB_MIN_TARGET_SIZE = 2
ABSORB_SIM = 0.42
# Second pass: merge cluster centroids that are still near each other.
CENTROID_MERGE_SIM = 0.48
# Soft cap so a 300-line track cannot become 40+ 声线 labels.
MAX_AUTO_SPEAKERS = 12
MIN_AUTO_SPEAKERS = 4
# Adjacent cues prefer the previous label only when embeddings are very close.
# Too low merges distinct talkers across a mixed cue boundary.
TEMPORAL_SIM = 0.70
# Cue-local Silero: a bit looser than ASR default so quiet lines still keep speech.
CLUSTER_VAD_THRESHOLD = 0.4
CLUSTER_VAD_MIN_SPEECH_MS = 150
ProgressCallback = Callable[[float, str], None]
SpeechInterval = tuple[float, float]


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


def intersect_span_with_speech(
    start_sec: float,
    end_sec: float,
    speech_intervals: Sequence[SpeechInterval] | None,
    *,
    min_sec: float = MIN_EMBED_SEC,
) -> list[SpeechInterval]:
    """Keep only the parts of ``[start,end]`` that overlap VAD speech."""
    lo = float(start_sec)
    hi = float(end_sec)
    if hi <= lo:
        return []
    floor = max(0.05, float(min_sec))
    if not speech_intervals:
        return [(lo, hi)] if (hi - lo) >= floor else []
    parts: list[SpeechInterval] = []
    for speech_lo, speech_hi in speech_intervals:
        a = max(lo, float(speech_lo))
        b = min(hi, float(speech_hi))
        if b - a >= floor:
            parts.append((a, b))
    return parts


def load_speech_intervals(
    waveform: np.ndarray,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> list[SpeechInterval]:
    """One Silero pass over the whole track. Empty list = caller keeps raw cue spans."""
    try:
        from src.core.asr.vad_segment import resolve_silero_vad_model_path, segment_speech

        if not resolve_silero_vad_model_path():
            return []
        segments = segment_speech(
            np.asarray(waveform, dtype=np.float32).reshape(-1),
            sample_rate=max(1, int(sample_rate)),
            threshold=CLUSTER_VAD_THRESHOLD,
            min_speech_duration_ms=CLUSTER_VAD_MIN_SPEECH_MS,
        )
    except Exception as exc:
        logger.warning("Speaker-cluster VAD failed; using raw cue spans: %s", exc)
        return []
    return [
        (float(item.start_sec), float(item.end_sec))
        for item in segments
        if float(item.end_sec) - float(item.start_sec) >= MIN_EMBED_SEC
    ]


def embed_windows_for_span(
    waveform: np.ndarray,
    *,
    start_sec: float,
    end_sec: float,
    sample_rate: int,
    max_windows: int | None = None,
    speech_intervals: Sequence[SpeechInterval] | None = None,
) -> list[tuple[np.ndarray, float]]:
    """Loudest non-overlapping CAM++ windows inside one ASR cue (VAD-trimmed when possible)."""
    limit = max(1, int(MAX_WINDOWS_PER_CUE if max_windows is None else max_windows))
    parts = intersect_span_with_speech(start_sec, end_sec, speech_intervals)
    if not parts:
        # No VAD hit inside the cue — fall back to the raw span so quiet lines still cluster.
        parts = [(float(start_sec), float(end_sec))]
    picked: list[tuple[np.ndarray, float]] = []
    for part_start, part_end in parts:
        if len(picked) >= limit:
            break
        room = limit - len(picked)
        picked.extend(
            _embed_windows_raw(
                waveform,
                start_sec=part_start,
                end_sec=part_end,
                sample_rate=sample_rate,
                max_windows=room,
            )
        )
    return picked[:limit]


def _embed_windows_raw(
    waveform: np.ndarray,
    *,
    start_sec: float,
    end_sec: float,
    sample_rate: int,
    max_windows: int,
) -> list[tuple[np.ndarray, float]]:
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
        if len(picked) >= max(1, int(max_windows)):
            break
    return [(piece, energy) for piece, energy, _pos in picked]


def _remap_labels_by_size(raw: list[int]) -> list[int]:
    counts: dict[int, int] = {}
    for label in raw:
        counts[label] = counts.get(label, 0) + 1
    ranked = sorted(counts, key=lambda label: (-counts[label], label))
    mapping = {old: index for index, old in enumerate(ranked)}
    return [mapping[label] for label in raw]


def _centroids_for_labels(
    embeddings: np.ndarray,
    labels: Sequence[int],
) -> dict[int, np.ndarray]:
    embs = l2_normalize(embeddings)
    groups: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        groups.setdefault(int(label), []).append(index)
    return {
        label: l2_normalize(embs[members].mean(axis=0, keepdims=True))[0]
        for label, members in groups.items()
        if members
    }


def _absorb_tiny_clusters(
    embeddings: np.ndarray,
    labels: list[int],
    *,
    max_size: int = ABSORB_MAX_SIZE,
    min_target: int = ABSORB_MIN_TARGET_SIZE,
    sim: float = ABSORB_SIM,
) -> list[int]:
    """Fold small fragments into the nearest larger voice when they still match."""
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
        centroids = _centroids_for_labels(embs, raw)
        big_mat = np.stack([centroids[label] for label in big], axis=0)
        moved = False
        for label in tiny:
            if label not in centroids:
                continue
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


def _merge_close_centroids(
    embeddings: np.ndarray,
    labels: list[int],
    *,
    sim: float = CENTROID_MERGE_SIM,
) -> list[int]:
    """Greedily merge cluster pairs whose centroids are still similar."""
    embs = l2_normalize(embeddings)
    raw = list(labels)
    cutoff = float(sim)
    for _ in range(max(1, len(set(raw)))):
        centroids = _centroids_for_labels(embs, raw)
        keys = sorted(centroids)
        if len(keys) < 2:
            break
        best_pair: tuple[int, int] | None = None
        best_score = -1.0
        for i, left in enumerate(keys):
            for right in keys[i + 1 :]:
                score = float(np.dot(centroids[left], centroids[right]))
                if score > best_score:
                    best_score = score
                    best_pair = (left, right)
        if best_pair is None or best_score < cutoff:
            break
        left, right = best_pair
        keep, drop = (left, right) if left < right else (right, left)
        raw = [keep if int(label) == drop else int(label) for label in raw]
    return raw


def _cap_cluster_count(
    embeddings: np.ndarray,
    labels: list[int],
    *,
    max_clusters: int,
) -> list[int]:
    """Force-merge nearest centroids until under ``max_clusters`` (last resort)."""
    embs = l2_normalize(embeddings)
    raw = list(labels)
    limit = max(1, int(max_clusters))
    while len(set(raw)) > limit:
        centroids = _centroids_for_labels(embs, raw)
        keys = sorted(centroids)
        if len(keys) < 2:
            break
        best_pair: tuple[int, int] | None = None
        best_score = -1.0
        for i, left in enumerate(keys):
            for right in keys[i + 1 :]:
                score = float(np.dot(centroids[left], centroids[right]))
                if score > best_score:
                    best_score = score
                    best_pair = (left, right)
        if best_pair is None:
            break
        left, right = best_pair
        keep, drop = (left, right) if left < right else (right, left)
        raw = [keep if int(label) == drop else int(label) for label in raw]
    return raw


def auto_speaker_budget(window_or_cue_count: int) -> int:
    """Soft upper bound for 声线N count — users will not rename dozens of labels."""
    n = max(0, int(window_or_cue_count))
    if n <= 0:
        return MIN_AUTO_SPEAKERS
    # ~one voice per 8–10 lines, clamped to a rename-friendly range.
    return max(MIN_AUTO_SPEAKERS, min(MAX_AUTO_SPEAKERS, max(MIN_AUTO_SPEAKERS, n // 8)))


def cluster_embeddings(
    embeddings: np.ndarray,
    *,
    threshold: float = COSINE_THRESHOLD,
    seed_order: list[int] | None = None,
    absorb_tiny: bool = True,
    consolidate: bool = True,
    max_clusters: int | None = None,
) -> list[int]:
    """Average-linkage clusters while mean pairwise cosine >= ``threshold``.

    ``seed_order`` is accepted for compatibility and ignored: linkage is global.
    ``consolidate`` absorbs fragments, merges close centroids, and soft-caps count.
    """
    del seed_order
    embs = l2_normalize(embeddings)
    count = int(embs.shape[0])
    if count <= 0:
        return []
    if count == 1:
        return [0]
    # float32 halves the N×N peak vs float64; cosine linkage does not need float64.
    sims = np.clip(embs @ embs.T, -1.0, 1.0).astype(np.float32, copy=False)
    np.fill_diagonal(sims, -np.inf)
    sizes = np.ones(count, dtype=np.float32)
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
    if absorb_tiny or consolidate:
        raw = _absorb_tiny_clusters(embs, raw)
    if consolidate:
        raw = _merge_close_centroids(embs, raw)
        if max_clusters is not None:
            raw = _cap_cluster_count(embs, raw, max_clusters=int(max_clusters))
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


def _max_windows_for_span(span_sec: float) -> int:
    if span_sec < 2.5:
        return 1
    if span_sec < 5.0:
        return 2
    return MAX_WINDOWS_PER_CUE


def _cluster_names_from_manuals(
    *,
    usable: Sequence[Mapping[str, Any]],
    window_cues: Sequence[int],
    window_labels: Sequence[int],
    window_energy: Sequence[float],
) -> dict[int, str]:
    """Map cluster id → manual speaker name when any named cue sits in that cluster."""
    votes: dict[int, dict[str, float]] = {}
    for cue_index, label, energy in zip(window_cues, window_labels, window_energy):
        item = usable[int(cue_index)]
        name = str(item.get("speaker") or "")
        if not item.get("is_manual") or not name:
            continue
        bucket = votes.setdefault(int(label), {})
        bucket[name] = float(bucket.get(name, 0.0)) + float(energy)
    named: dict[int, str] = {}
    for label, bucket in votes.items():
        if not bucket:
            continue
        named[int(label)] = max(bucket.items(), key=lambda pair: (pair[1], pair[0]))[0]
    return named


def _auto_label_map(window_labels: Sequence[int], named_clusters: Mapping[int, str]) -> dict[int, int]:
    """Remap unnamed clusters to 声线 indices by size (named clusters keep their names)."""
    counts: dict[int, int] = {}
    for label in window_labels:
        key = int(label)
        if key in named_clusters:
            continue
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts, key=lambda label: (-counts[label], label))
    return {old: index for index, old in enumerate(ranked)}


def _cue_embedding_centroids(
    window_vectors: Sequence[np.ndarray],
    window_cues: Sequence[int],
    window_energy: Sequence[float],
    *,
    cue_count: int,
) -> list[np.ndarray | None]:
    totals = [None] * max(0, int(cue_count))
    weights = [0.0] * max(0, int(cue_count))
    for vector, cue_index, energy in zip(window_vectors, window_cues, window_energy):
        index = int(cue_index)
        if index < 0 or index >= len(totals):
            continue
        vec = np.asarray(vector, dtype=np.float32).reshape(-1)
        weight = max(1.0e-3, float(energy))
        if totals[index] is None:
            totals[index] = vec * weight
        else:
            totals[index] = totals[index] + vec * weight
        weights[index] += weight
    out: list[np.ndarray | None] = []
    for total, weight in zip(totals, weights):
        if total is None or weight <= 0:
            out.append(None)
            continue
        out.append(l2_normalize(total / weight)[0])
    return out


def _apply_temporal_speaker_smooth(
    draft: Sequence[tuple[int, str, int]],
    cue_centroids: Sequence[np.ndarray | None],
    *,
    sim: float = TEMPORAL_SIM,
) -> dict[int, str]:
    """Prefer the previous auto-label when adjacent embeddings are nearly the same voice."""
    assignments: dict[int, str] = {}
    prev_name = ""
    prev_centroid: np.ndarray | None = None
    cutoff = float(sim)
    for cue_index, name, seg_index in draft:
        label = str(name or "")
        centroid = None
        if 0 <= int(cue_index) < len(cue_centroids):
            centroid = cue_centroids[int(cue_index)]
        if (
            prev_name
            and label
            and label != prev_name
            and is_auto_speaker_label(prev_name)
            and is_auto_speaker_label(label)
            and prev_centroid is not None
            and centroid is not None
            and float(np.dot(prev_centroid, centroid)) >= cutoff
        ):
            label = prev_name
        if label:
            assignments[int(seg_index)] = label
            prev_name = label
            if centroid is not None:
                prev_centroid = centroid
    return assignments


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
    segments: list[dict[str, Any]] | None = None,
    persist: bool = True,
    speech_intervals: Sequence[SpeechInterval] | None = None,
) -> dict[str, Any]:
    """Fill empty / auto speaker labels from CAM++ clusters. Manual names stay.

    Manual cues are embedded as anchors: unlabeled cues that land in the same
    cluster inherit that name. Hard-sub OCR cues use on-screen time as audio window.
    """
    from src.core.understanding.base import UnderstandingStoppedError

    vid = str(video_id or "").strip()
    if not vid:
        return {"ok": False, "error": "missing video_id", "labeled": 0, "skipped": 0, "speakers": 0}

    def _stopped() -> bool:
        return bool(stop_callback and stop_callback())

    def _progress(value: float, stage: str) -> None:
        if progress_callback:
            progress_callback(float(value), stage)

    supplied_segments = segments is not None
    if supplied_segments:
        payload = {
            "video_path": str(video_path or ""),
            "library_path": "",
            "asr_source": "",
        }
        segments = list(segments or [])
    else:
        payload = load_dialogue_transcript(vid, config=config) or {}
        segments = list(payload.get("segments") or [])
    # Embed manuals + unlabeled together; only unlabeled rows are rewritten.
    embed_items: list[dict[str, Any]] = []
    skipped_manual = 0
    skipped_short = 0
    unlabeled_count = 0
    for index, row in enumerate(segments):
        if not isinstance(row, dict):
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
        is_manual = bool(speaker) and not is_auto_speaker_label(speaker)
        if is_manual:
            skipped_manual += 1
        if (end - start) < MIN_EMBED_SEC:
            skipped_short += 1
            continue
        if not is_manual:
            unlabeled_count += 1
        embed_items.append(
            {
                "seg_index": seg_index,
                "start": start,
                "end": end,
                "speaker": speaker,
                "is_manual": is_manual,
            }
        )
    if unlabeled_count <= 0:
        return {
            "ok": True,
            "labeled": 0,
            "skipped": skipped_manual,
            "speakers": 0,
            "video_id": vid,
            "reason": "short" if skipped_short else "empty",
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
        if (
            persist
            and not supplied_segments
            and stored
            and os.path.normcase(os.path.normpath(stored)) != os.path.normcase(media)
        ):
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

    if speech_intervals is None:
        _progress(0.08, "vad")
        speech_intervals = load_speech_intervals(audio, sample_rate=sr)
    else:
        speech_intervals = list(speech_intervals)

    embed = embed_fn
    if embed is None:
        engine = get_campplus_engine()

        def embed(wav, _engine=engine):
            return _engine.embed_waveform(wav, sample_rate=sr)

    window_vectors: list[np.ndarray] = []
    window_energy: list[float] = []
    window_cues: list[int] = []
    usable: list[dict[str, Any]] = []
    total = len(embed_items)
    for index, item in enumerate(embed_items):
        if _stopped():
            raise UnderstandingStoppedError("stopped")
        span_sec = float(item["end"]) - float(item["start"])
        windows = embed_windows_for_span(
            audio,
            start_sec=item["start"],
            end_sec=item["end"],
            sample_rate=sr,
            max_windows=_max_windows_for_span(span_sec),
            speech_intervals=speech_intervals,
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

    unlabeled_usable = [item for item in usable if not item.get("is_manual")]
    if not unlabeled_usable or not window_vectors:
        return {
            "ok": True,
            "labeled": 0,
            "skipped": skipped_manual,
            "speakers": 0,
            "video_id": vid,
            "reason": "quiet",
        }

    manual_name_count = len(
        {str(item.get("speaker") or "") for item in embed_items if item.get("is_manual") and item.get("speaker")}
    )
    speaker_cap = auto_speaker_budget(unlabeled_count) + manual_name_count
    seed_order = sorted(range(len(window_vectors)), key=lambda index: -window_energy[index])
    window_labels = cluster_embeddings(
        np.stack(window_vectors, axis=0),
        seed_order=seed_order,
        max_clusters=speaker_cap,
    )
    named_clusters = _cluster_names_from_manuals(
        usable=usable,
        window_cues=window_cues,
        window_labels=window_labels,
        window_energy=window_energy,
    )
    auto_map = _auto_label_map(window_labels, named_clusters)
    # Majority vote per cue (energy as tie-break). One loud SFX window must not
    # override two consistent speech windows from the same talker.
    votes: list[dict[int, float]] = [dict() for _ in usable]
    for cue_index, label, energy in zip(window_cues, window_labels, window_energy):
        bucket = votes[cue_index]
        key = int(label)
        bucket[key] = float(bucket.get(key, 0.0)) + float(energy)
    cue_centroids = _cue_embedding_centroids(
        window_vectors,
        window_cues,
        window_energy,
        cue_count=len(usable),
    )
    draft: list[tuple[int, str, int]] = []  # (cue_index, label, seg_index)
    for cue_index, (item, bucket) in enumerate(zip(usable, votes)):
        if item.get("is_manual") or not bucket:
            continue
        best_label = max(
            bucket.items(),
            key=lambda pair: (pair[1], -pair[0]),
        )[0]
        if best_label in named_clusters:
            name = named_clusters[best_label]
        else:
            auto_index = auto_map.get(best_label)
            if auto_index is None:
                continue
            name = speaker_cluster_label(auto_index)
        draft.append((cue_index, name, int(item["seg_index"])))
    draft.sort(key=lambda row: (float(usable[row[0]]["start"]), row[2]))
    assignments = _apply_temporal_speaker_smooth(draft, cue_centroids)
    if persist:
        updated = update_dialogue_segment_speakers(vid, assignments, config=config)
    else:
        updated = len(assignments)
    speaker_count = len({label for label in assignments.values()})
    _progress(1.0, "done")
    return {
        "ok": True,
        "labeled": int(updated),
        "skipped": skipped_manual,
        "speakers": speaker_count,
        "video_id": vid,
        "assignments": dict(assignments),
        "anchored": sum(1 for label in assignments.values() if not is_auto_speaker_label(label)),
        "vad_spans": len(speech_intervals or []),
        "speaker_cap": int(speaker_cap),
    }
