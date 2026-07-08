"""Locate / crop telemetry recording and CLIP window bias auto-tune."""

from __future__ import annotations

import os

from src.services.locate_segmentation_gating import (
    MIN_BIAS_SEGMENT_BUCKET_SAMPLES,
    MIN_BIAS_SEGMENT_ERRORS,
    MIN_RELIABLE_BUCKET_SAMPLES,
    P90_EFFECT_SIZE_MIN_SEC,
    passes_effect_size_gate,
)
from src.services.search_telemetry_store import (
    LOCATE_CLIP_BIAS_MAX_SEC,
    LOCATE_CLIP_BIAS_SEGMENT_INTERVAL,
    LOCATE_CLIP_BIAS_STEP_SEC,
    LOCATE_CLIP_ERROR_SAMPLE_CAP,
    LOCATE_CLIP_P90_HIGH_SEC,
    LOCATE_CLIP_P90_LOW_SEC,
    LOCATE_CLIP_SIGNAL_SAMPLE_CAP,
    SUMMARY_LOG_INTERVAL,
    SearchTelemetryState,
    _ensure_state_locked,
    _lock,
    _log_summary_locked,
    _maybe_add_profile_counter,
    _now,
    _percentile,
    _persist_locked,
    is_locate_bias_auto_tune_enabled,
    is_telemetry_enabled,
    logger,
)

def record_crop_locate_anchor(
    *,
    anchor_sec: float,
    result_sec: float,
    anchor_kept: bool,
    best_sec: float | None = None,
    best_score: float | None = None,
    anchor_score: float | None = None,
    clip_score: float | None = None,
    video_path: str = "",
) -> None:
    if not is_telemetry_enabled():
        return

    kept = bool(anchor_kept)
    with _lock:
        state = _ensure_state_locked()
        state.crop_locate_total += 1
        if kept:
            state.crop_locate_anchor_kept += 1
        else:
            state.crop_locate_anchor_moved += 1
        state.updated_at = _now()
        _persist_locked(state)
        total = state.crop_locate_total

    gain = None
    if best_score is not None and anchor_score is not None:
        gain = float(best_score) - float(anchor_score)

    logger.info(
        "crop_locate_anchor kept=%s anchor=%.3f result=%.3f best=%.3f gain=%s score=%s video=%s",
        int(kept),
        float(anchor_sec),
        float(result_sec),
        float(best_sec if best_sec is not None else result_sec),
        "na" if gain is None else f"{gain:.4f}",
        "na" if clip_score is None else f"{float(clip_score):.4f}",
        os.path.basename(str(video_path or "")) or "-",
    )
    _maybe_add_profile_counter("telemetry_crop_locate_total")
    _maybe_add_profile_counter("telemetry_crop_locate_anchor_kept" if kept else "telemetry_crop_locate_anchor_moved")
    if total % SUMMARY_LOG_INTERVAL == 0:
        _log_summary_locked()


def _locate_score_bucket(score: float | None) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if value >= 0.9:
        return "0.9+"
    if value >= 0.8:
        return "0.8"
    if value >= 0.7:
        return "0.7"
    if value >= 0.6:
        return "0.6"
    return "<0.6"


def _locate_margin_bucket(margin: float | None) -> str:
    try:
        value = float(margin)
    except (TypeError, ValueError):
        return "unknown"
    if value >= 0.10:
        return "0.10+"
    if value >= 0.05:
        return "0.05"
    return "<0.05"


def get_locate_clip_window_bias_sec(config=None, score: float | None = None) -> float:
    if not is_telemetry_enabled(config) or not is_locate_bias_auto_tune_enabled(config):
        return 0.0
    score_bucket = _locate_score_bucket(score) if score is not None else None
    with _lock:
        state = _ensure_state_locked()
        if score_bucket:
            segmented = state.locate_clip_bias_by_score.get(score_bucket)
            if segmented is not None and _segmented_bias_is_justified(state, score_bucket):
                return float(segmented)
        return float(state.locate_clip_bias_sec)


def _score_bucket_sample_count(state: SearchTelemetryState, score_bucket: str) -> int:
    total = 0
    prefix = f"score={score_bucket}|"
    for key, stats in state.locate_clip_bucket_stats.items():
        if str(key).startswith(prefix):
            total += int(stats.get("samples", 0) or 0)
    return total


def _errors_for_score_bucket(state: SearchTelemetryState, score_bucket: str) -> list[float]:
    errors: list[float] = []
    for sample in state.locate_clip_signal_samples:
        if str(sample.get("score_bucket") or "") != score_bucket:
            continue
        try:
            errors.append(max(0.0, float(sample.get("error_sec", 0.0))))
        except (TypeError, ValueError):
            continue
    return errors


def _all_signal_errors(state: SearchTelemetryState) -> list[float]:
    errors: list[float] = []
    for sample in state.locate_clip_signal_samples:
        try:
            errors.append(max(0.0, float(sample.get("error_sec", 0.0))))
        except (TypeError, ValueError):
            continue
    return errors


def _list_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values)) / float(len(values))


def _segmented_bias_is_justified(state: SearchTelemetryState, score_bucket: str) -> bool:
    segment_errors = _errors_for_score_bucket(state, score_bucket)
    global_errors = _all_signal_errors(state)
    if (
        len(segment_errors) < MIN_BIAS_SEGMENT_ERRORS
        or len(global_errors) < MIN_RELIABLE_BUCKET_SAMPLES
        or _score_bucket_sample_count(state, score_bucket) < MIN_BIAS_SEGMENT_BUCKET_SAMPLES
    ):
        return False
    return passes_effect_size_gate(
        segment_mean=_list_mean(segment_errors),
        global_mean=_list_mean(global_errors),
        segment_p90=_percentile(segment_errors, 90),
        global_p90=_percentile(global_errors, 90),
    )


def _adjust_segmented_bias_locked(state: SearchTelemetryState, score_bucket: str) -> None:
    if not _segmented_bias_is_justified(state, score_bucket):
        return
    errors = _errors_for_score_bucket(state, score_bucket)
    global_errors = _all_signal_errors(state)
    p90 = _percentile(errors, 90)
    global_p90 = _percentile(global_errors, 90)
    if p90 is None or global_p90 is None:
        return

    current = float(state.locate_clip_bias_by_score.get(score_bucket, state.locate_clip_bias_sec))
    if p90 > LOCATE_CLIP_P90_HIGH_SEC and (p90 - global_p90) >= P90_EFFECT_SIZE_MIN_SEC:
        current = min(LOCATE_CLIP_BIAS_MAX_SEC, current + LOCATE_CLIP_BIAS_STEP_SEC)
    elif p90 < LOCATE_CLIP_P90_LOW_SEC and (global_p90 - p90) >= P90_EFFECT_SIZE_MIN_SEC:
        current = max(0.0, current - LOCATE_CLIP_BIAS_STEP_SEC)
    else:
        return
    state.locate_clip_bias_by_score[str(score_bucket)] = float(current)


def record_locate_clip_window(
    *,
    window_sec: float,
    score: float | None,
    margin: float | None,
    anchor_sec: float,
    result_sec: float,
    is_crop: bool = False,
    confidence: float | None = None,
    video_pace: str = "unknown",
) -> None:
    if not is_telemetry_enabled():
        return

    final_error = abs(float(result_sec) - float(anchor_sec))
    score_bucket = _locate_score_bucket(score)
    pace = str(video_pace or "unknown")
    bucket_key = (
        f"score={score_bucket}|"
        f"margin={_locate_margin_bucket(margin)}|"
        f"window={int(round(float(window_sec)))}|"
        f"pace={pace}|"
        f"crop={int(bool(is_crop))}"
    )

    with _lock:
        state = _ensure_state_locked()
        state.locate_clip_samples += 1
        state.locate_clip_error_samples.append(final_error)
        if len(state.locate_clip_error_samples) > LOCATE_CLIP_ERROR_SAMPLE_CAP:
            state.locate_clip_error_samples = state.locate_clip_error_samples[-LOCATE_CLIP_ERROR_SAMPLE_CAP:]
        state.locate_clip_signal_samples.append(
            {
                "score": float(score) if score is not None else -1.0,
                "margin": float(margin) if margin is not None else -1.0,
                "confidence": float(confidence) if confidence is not None else -1.0,
                "error_sec": final_error,
                "window_sec": float(window_sec),
                "score_bucket": score_bucket,
                "pace": pace,
            }
        )
        if len(state.locate_clip_signal_samples) > LOCATE_CLIP_SIGNAL_SAMPLE_CAP:
            state.locate_clip_signal_samples = state.locate_clip_signal_samples[-LOCATE_CLIP_SIGNAL_SAMPLE_CAP:]
        bucket = state.locate_clip_bucket_stats.setdefault(
            bucket_key,
            {"samples": 0, "error_sum_sec": 0.0},
        )
        bucket["samples"] = int(bucket.get("samples", 0) or 0) + 1
        bucket["error_sum_sec"] = float(bucket.get("error_sum_sec", 0.0) or 0.0) + final_error

        bucket_samples = _score_bucket_sample_count(state, score_bucket)
        if (
            is_locate_bias_auto_tune_enabled()
            and bucket_samples > 0
            and bucket_samples % LOCATE_CLIP_BIAS_SEGMENT_INTERVAL == 0
        ):
            _adjust_segmented_bias_locked(state, score_bucket)

        segmented = state.locate_clip_bias_by_score.get(score_bucket)
        bias = float(segmented if segmented is not None else state.locate_clip_bias_sec)
        state.updated_at = _now()
        _persist_locked(state)

    logger.info(
        "locate_clip_window window=%.0fs score=%s margin=%s confidence=%s pace=%s anchor=%.3f result=%.3f error=%.3fs bias=%.0fs crop=%s",
        float(window_sec),
        "na" if score is None else f"{float(score):.4f}",
        "na" if margin is None else f"{float(margin):.4f}",
        "na" if confidence is None else f"{float(confidence):.4f}",
        pace,
        float(anchor_sec),
        float(result_sec),
        final_error,
        bias,
        int(bool(is_crop)),
    )
    _maybe_add_profile_counter("telemetry_locate_clip_samples")
