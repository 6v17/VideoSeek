from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Sequence

MIN_RELIABLE_BUCKET_SAMPLES = 30
MIN_SEGMENT_GROUP_SAMPLES = 10
MIN_BIAS_SEGMENT_ERRORS = 10
MIN_BIAS_SEGMENT_BUCKET_SAMPLES = 50
EFFECT_SIZE_MIN_SEC = 0.75
P90_EFFECT_SIZE_MIN_SEC = 1.0
MIN_CORRELATION_SAMPLES = 30
MIN_CORRELATION_EFFECT = 0.15


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return float(sum(values)) / float(len(values))


def passes_effect_size_gate(
    *,
    segment_mean: float | None,
    global_mean: float | None,
    segment_p90: float | None,
    global_p90: float | None,
) -> bool:
    if segment_mean is None or global_mean is None:
        return False
    mean_delta = abs(float(segment_mean) - float(global_mean))
    if mean_delta >= EFFECT_SIZE_MIN_SEC:
        return True
    if segment_p90 is None or global_p90 is None:
        return False
    return abs(float(segment_p90) - float(global_p90)) >= P90_EFFECT_SIZE_MIN_SEC


def prediction_mae(
    samples: Sequence[dict[str, Any]],
    *,
    group_key: Callable[[dict[str, Any]], str],
) -> tuple[float | None, dict[str, dict[str, float | int]]]:
    if not samples:
        return None, {}

    group_errors: dict[str, list[float]] = defaultdict(list)
    for sample in samples:
        try:
            error = max(0.0, float(sample.get("error_sec", 0.0)))
        except (TypeError, ValueError):
            continue
        group_errors[str(group_key(sample))].append(error)

    if not group_errors:
        return None, {}

    group_stats: dict[str, dict[str, float | int]] = {}
    group_means: dict[str, float] = {}
    for label, errors in group_errors.items():
        mean_error = _mean(errors)
        if mean_error is None:
            continue
        group_stats[label] = {
            "samples": len(errors),
            "mean_error_sec": mean_error,
        }
        group_means[label] = mean_error

    total_mae = 0.0
    total_count = 0
    for sample in samples:
        try:
            error = max(0.0, float(sample.get("error_sec", 0.0)))
        except (TypeError, ValueError):
            continue
        label = str(group_key(sample))
        predicted = group_means.get(label)
        if predicted is None:
            continue
        total_mae += abs(error - predicted)
        total_count += 1

    if total_count <= 0:
        return None, group_stats
    return total_mae / float(total_count), group_stats


def merged_baseline_mae(samples: Sequence[dict[str, Any]]) -> float | None:
    errors: list[float] = []
    for sample in samples:
        try:
            errors.append(max(0.0, float(sample.get("error_sec", 0.0))))
        except (TypeError, ValueError):
            continue
    global_mean = _mean(errors)
    if global_mean is None:
        return None
    return sum(abs(error - global_mean) for error in errors) / float(len(errors))


def analyze_dimension_collapse(
    samples: Sequence[dict[str, Any]],
    *,
    dimension: str,
    group_key: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    usable = list(samples)
    total = len(usable)
    baseline_mae = merged_baseline_mae(usable)
    segmented_mae, group_stats = prediction_mae(usable, group_key=group_key)

    sparse_groups = [
        label
        for label, stats in group_stats.items()
        if int(stats.get("samples", 0) or 0) < MIN_SEGMENT_GROUP_SAMPLES
    ]
    reliable_groups = [
        label
        for label, stats in group_stats.items()
        if int(stats.get("samples", 0) or 0) >= MIN_SEGMENT_GROUP_SAMPLES
    ]

    improvement = None
    if baseline_mae is not None and segmented_mae is not None:
        improvement = float(baseline_mae) - float(segmented_mae)

    verdict = "insufficient_data"
    if total < MIN_RELIABLE_BUCKET_SAMPLES or baseline_mae is None or segmented_mae is None:
        verdict = "insufficient_data"
    elif sparse_groups:
        verdict = "collapse_sparse_buckets"
    elif improvement is not None and improvement >= EFFECT_SIZE_MIN_SEC:
        verdict = "keep_segmentation"
    elif improvement is not None and improvement <= -EFFECT_SIZE_MIN_SEC:
        verdict = "collapse_harms"
    else:
        verdict = "collapse_no_effect"

    return {
        "dimension": dimension,
        "samples": total,
        "baseline_mae_sec": baseline_mae,
        "segmented_mae_sec": segmented_mae,
        "improvement_sec": improvement,
        "sparse_groups": sparse_groups,
        "reliable_groups": reliable_groups,
        "verdict": verdict,
        "effect_size_threshold_sec": EFFECT_SIZE_MIN_SEC,
    }


def confidence_band(sample: dict[str, Any]) -> str:
    try:
        value = float(sample.get("confidence", -1.0))
    except (TypeError, ValueError):
        return "unknown"
    if value < 0.0:
        return "unknown"
    if value >= 0.95:
        return "high"
    if value >= 0.75:
        return "medium"
    return "low"
