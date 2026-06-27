from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from src.app.logging_utils import get_app_data_dir

from src.services.locate_segmentation_gating import (
    EFFECT_SIZE_MIN_SEC,
    MIN_CORRELATION_EFFECT,
    MIN_CORRELATION_SAMPLES,
    MIN_RELIABLE_BUCKET_SAMPLES,
    analyze_dimension_collapse,
    confidence_band,
    merged_baseline_mae,
)
from src.services.locate_telemetry_utils import pearson_correlation
from src.services.search_telemetry import (
    get_locate_signal_samples,
    get_telemetry_file_path,
    get_telemetry_summary,
    reload_telemetry_state,
)

_FIXED_BASELINE_WINDOW_SEC = 30.0
_ANALYSIS_HISTORY_CAP = 50
_STABILITY_MIN_SNAPSHOTS = 3
_STABILITY_AGREEMENT_RATIO = 0.67
_STABILITY_BASELINE_MAE_STD_MAX = 0.75
_UPGRADE_MIN_CONFIRM_SNAPSHOTS = 5
_UPGRADE_AGREEMENT_RATIO = 0.67
_DIAGNOSTIC_POLICY = "diagnostic_only"
_UPGRADE_POLICY = "version_control_not_self_optimization"


def analyze_confidence_predictiveness(
    signal_samples: list[dict[str, float | str]] | None = None,
) -> dict[str, Any]:
    samples = list(signal_samples if signal_samples is not None else get_locate_signal_samples())
    usable = [
        sample
        for sample in samples
        if float(sample.get("score", -1.0)) >= 0.0
        and float(sample.get("margin", -1.0)) >= 0.0
        and float(sample.get("confidence", -1.0)) >= 0.0
    ]
    errors = [float(sample["error_sec"]) for sample in usable]
    scores = [float(sample["score"]) for sample in usable]
    margins = [float(sample["margin"]) for sample in usable]
    confidences = [float(sample["confidence"]) for sample in usable]

    corr_score = pearson_correlation(scores, errors)
    corr_margin = pearson_correlation(margins, errors)
    corr_confidence = pearson_correlation(confidences, errors)

    predictors = {
        "score": corr_score,
        "margin": corr_margin,
        "confidence": corr_confidence,
    }
    ranked = sorted(
        (
            (name, value)
            for name, value in predictors.items()
            if value is not None
        ),
        key=lambda item: abs(float(item[1])),
        reverse=True,
    )
    best_name = ranked[0][0] if ranked else None
    verdict = "insufficient_data"
    if len(usable) >= MIN_CORRELATION_SAMPLES and best_name:
        best_corr = predictors.get(best_name)
        if best_corr is None or abs(float(best_corr)) < MIN_CORRELATION_EFFECT:
            verdict = "no_significant_correlation"
        elif best_name == "confidence" and corr_confidence is not None and corr_score is not None:
            if abs(corr_confidence) > abs(corr_score) + MIN_CORRELATION_EFFECT:
                verdict = "confidence_beats_score"
            elif abs(corr_confidence) + MIN_CORRELATION_EFFECT < abs(corr_score):
                verdict = "score_beats_confidence"
            else:
                verdict = "confidence_similar_to_score"
        else:
            verdict = f"{best_name}_significant"

    scatter: list[dict[str, Any]] = []
    for sample in usable:
        scatter.append(
            {
                "confidence": float(sample["confidence"]),
                "error_sec": float(sample["error_sec"]),
                "pace": str(sample.get("pace") or "unknown"),
            }
        )

    return {
        "samples": len(usable),
        "min_samples": MIN_CORRELATION_SAMPLES,
        "min_correlation_effect": MIN_CORRELATION_EFFECT,
        "correlation_error_score": corr_score,
        "correlation_error_margin": corr_margin,
        "correlation_error_confidence": corr_confidence,
        "best_predictor": best_name,
        "verdict": verdict,
        "scatter_confidence_error": scatter[-200:],
    }


def _aggregate_cross_tab(
    bucket_stats: dict[str, dict[str, float | int]],
    *,
    left: str,
    right: str,
    skip_crop: bool = True,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, float | int]] = defaultdict(
        lambda: {"samples": 0, "error_sum_sec": 0.0},
    )
    for key, stats in dict(bucket_stats or {}).items():
        parsed = parse_locate_bucket_key(key)
        if skip_crop and parsed.get("crop") == "1":
            continue
        label = (str(parsed.get(left) or "unknown"), str(parsed.get(right) or "unknown"))
        samples = int(stats.get("samples", 0) or 0)
        if samples <= 0:
            continue
        bucket = grouped[label]
        bucket["samples"] = int(bucket["samples"]) + samples
        bucket["error_sum_sec"] = float(bucket["error_sum_sec"]) + float(stats.get("error_sum_sec", 0.0) or 0.0)

    rows: list[dict[str, Any]] = []
    for (left_label, right_label), stats in sorted(grouped.items()):
        samples = int(stats.get("samples", 0) or 0)
        rows.append(
            {
                left: left_label,
                right: right_label,
                "samples": samples,
                "mean_error_sec": _mean_error(stats),
                "reliable": samples >= MIN_RELIABLE_BUCKET_SAMPLES,
            }
        )
    return rows


def analyze_segmentation_collapse_test(
    signal_samples: list[dict[str, float | str]] | None = None,
) -> dict[str, Any]:
    samples = [
        sample
        for sample in list(signal_samples if signal_samples is not None else get_locate_signal_samples())
        if float(sample.get("error_sec", -1.0)) >= 0.0
    ]
    baseline_mae = merged_baseline_mae(samples)
    dimensions = [
        analyze_dimension_collapse(
            samples,
            dimension="pace",
            group_key=lambda sample: str(sample.get("pace") or "unknown"),
        ),
        analyze_dimension_collapse(
            samples,
            dimension="score_bucket",
            group_key=lambda sample: str(sample.get("score_bucket") or "unknown"),
        ),
        analyze_dimension_collapse(
            samples,
            dimension="confidence_band",
            group_key=confidence_band,
        ),
    ]

    keep = [item["dimension"] for item in dimensions if item.get("verdict") == "keep_segmentation"]
    collapse = [
        item["dimension"]
        for item in dimensions
        if str(item.get("verdict") or "").startswith("collapse")
    ]
    if len(samples) < MIN_RELIABLE_BUCKET_SAMPLES:
        overall = "insufficient_data"
    elif keep and collapse:
        overall = "segmentation_partially_justified"
    elif keep:
        overall = "segmentation_partially_justified"
    elif collapse:
        overall = "prefer_merged_baseline"
    else:
        overall = "inconclusive"

    fragmentation_warning = bool(keep) and (
        overall in {"prefer_merged_baseline", "inconclusive"} or bool(collapse)
    )

    return {
        "samples": len(samples),
        "baseline_mae_sec": baseline_mae,
        "effect_size_threshold_sec": EFFECT_SIZE_MIN_SEC,
        "min_reliable_samples": MIN_RELIABLE_BUCKET_SAMPLES,
        "dimensions": dimensions,
        "keep_dimensions": keep,
        "collapse_dimensions": collapse,
        "overall_verdict": overall,
        "fragmentation_warning": fragmentation_warning,
        "advisory_only": True,
        "runtime_decision_impact": "none",
    }


def parse_locate_bucket_key(key: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for segment in str(key or "").split("|"):
        if "=" not in segment:
            continue
        name, value = segment.split("=", 1)
        parts[name.strip()] = value.strip()
    return parts


def _aggregate_dimension(
    bucket_stats: dict[str, dict[str, float | int]],
    *,
    dimension: str,
    skip_crop: bool = True,
) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"samples": 0, "error_sum_sec": 0.0},
    )
    for key, stats in dict(bucket_stats or {}).items():
        parsed = parse_locate_bucket_key(key)
        if skip_crop and parsed.get("crop") == "1":
            continue
        label = str(parsed.get(dimension) or "unknown")
        samples = int(stats.get("samples", 0) or 0)
        error_sum = float(stats.get("error_sum_sec", 0.0) or 0.0)
        if samples <= 0:
            continue
        bucket = grouped[label]
        bucket["samples"] = int(bucket["samples"]) + samples
        bucket["error_sum_sec"] = float(bucket["error_sum_sec"]) + error_sum
    return dict(grouped)


def _mean_error(stats: dict[str, float | int]) -> float | None:
    samples = int(stats.get("samples", 0) or 0)
    if samples <= 0:
        return None
    return float(stats.get("error_sum_sec", 0.0) or 0.0) / float(samples)


def analyze_locate_window_stats(summary: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(summary or get_telemetry_summary())
    locate = dict(payload.get("locate_clip_window") or {})
    bucket_stats = dict(locate.get("bucket_stats") or {})

    by_window = _aggregate_dimension(bucket_stats, dimension="window")
    by_score = _aggregate_dimension(bucket_stats, dimension="score")
    by_margin = _aggregate_dimension(bucket_stats, dimension="margin")
    by_pace = _aggregate_dimension(bucket_stats, dimension="pace")
    window_pace_rows = _aggregate_cross_tab(bucket_stats, left="window", right="pace")

    total_samples = int(locate.get("samples", 0) or 0)
    overall_error_samples = locate.get("p90_anchor_error_sec")

    window_rows: list[dict[str, Any]] = []
    for window_label, stats in sorted(by_window.items(), key=lambda item: _window_sort_key(item[0])):
        samples = int(stats.get("samples", 0) or 0)
        mean_error = _mean_error(stats)
        window_rows.append(
            {
                "window_sec": window_label,
                "samples": samples,
                "mean_error_sec": mean_error,
                "reliable": samples >= MIN_RELIABLE_BUCKET_SAMPLES,
            }
        )

    score_rows = []
    for score_label, stats in sorted(by_score.items()):
        samples = int(stats.get("samples", 0) or 0)
        score_rows.append(
            {
                "score_bucket": score_label,
                "samples": samples,
                "mean_error_sec": _mean_error(stats),
                "reliable": samples >= MIN_RELIABLE_BUCKET_SAMPLES,
            }
        )

    margin_rows = []
    for margin_label, stats in sorted(by_margin.items()):
        samples = int(stats.get("samples", 0) or 0)
        margin_rows.append(
            {
                "margin_bucket": margin_label,
                "samples": samples,
                "mean_error_sec": _mean_error(stats),
                "reliable": samples >= MIN_RELIABLE_BUCKET_SAMPLES,
            }
        )

    pace_rows = []
    for pace_label, stats in sorted(by_pace.items()):
        samples = int(stats.get("samples", 0) or 0)
        pace_rows.append(
            {
                "pace_bucket": pace_label,
                "samples": samples,
                "mean_error_sec": _mean_error(stats),
                "reliable": samples >= MIN_RELIABLE_BUCKET_SAMPLES,
            }
        )

    recommendation = _recommend_window_policy(by_window, by_score, bucket_stats)
    confidence_analysis = analyze_confidence_predictiveness()
    segmentation_collapse = analyze_segmentation_collapse_test()
    diagnostic_policy = build_diagnostic_policy()
    return {
        "policy": diagnostic_policy,
        "total_samples": total_samples,
        "bias_sec": float(locate.get("bias_sec", 0.0) or 0.0),
        "bias_by_score": dict(locate.get("bias_by_score") or {}),
        "p50_anchor_error_sec": locate.get("p50_anchor_error_sec"),
        "p90_anchor_error_sec": overall_error_samples,
        "by_window": window_rows,
        "by_score": score_rows,
        "by_margin": margin_rows,
        "by_pace": pace_rows,
        "window_x_pace": window_pace_rows,
        "confidence_analysis": confidence_analysis,
        "segmentation_collapse": segmentation_collapse,
        "recommendation": recommendation,
        "telemetry_path": get_telemetry_file_path(),
        "telemetry_exists": os.path.isfile(get_telemetry_file_path()),
        "analysis_history_path": get_analysis_history_path(),
    }


def build_diagnostic_policy() -> dict[str, Any]:
    from src.services.search_telemetry import is_locate_bias_auto_tune_enabled

    return {
        "mode": _DIAGNOSTIC_POLICY,
        "runtime_decision_impact": "none",
        "bias_auto_tune_enabled": bool(is_locate_bias_auto_tune_enabled()),
        "guidance": (
            "Diagnostic only. upgrade_gate marks collapse-test candidates for manual version changes."
        ),
    }


def get_analysis_history_path() -> str:
    return os.path.join(get_app_data_dir(), "telemetry", "locate_analysis_history.json")


def _analysis_snapshot_from_report(analysis: dict[str, Any]) -> dict[str, Any]:
    collapse = dict(analysis.get("segmentation_collapse") or {})
    recommendation = dict(analysis.get("recommendation") or {})
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_samples": int(analysis.get("total_samples", 0) or 0),
        "baseline_mae_sec": collapse.get("baseline_mae_sec"),
        "overall_verdict": collapse.get("overall_verdict"),
        "keep_dimensions": list(collapse.get("keep_dimensions") or []),
        "collapse_dimensions": list(collapse.get("collapse_dimensions") or []),
        "fragmentation_warning": bool(collapse.get("fragmentation_warning")),
        "adaptive_vs_fixed_verdict": recommendation.get("verdict"),
        "dimension_verdicts": {
            str(row.get("dimension")): str(row.get("verdict"))
            for row in (collapse.get("dimensions") or [])
            if row.get("dimension")
        },
    }


def load_analysis_history() -> list[dict[str, Any]]:
    path = get_analysis_history_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        history = payload.get("snapshots") if isinstance(payload, dict) else payload
        if not isinstance(history, list):
            return []
        return [dict(item) for item in history if isinstance(item, dict)]
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []


def record_analysis_snapshot(analysis: dict[str, Any]) -> dict[str, Any]:
    snapshot = _analysis_snapshot_from_report(analysis)
    history = load_analysis_history()
    history.append(snapshot)
    if len(history) > _ANALYSIS_HISTORY_CAP:
        history = history[-_ANALYSIS_HISTORY_CAP:]

    path = get_analysis_history_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    payload = {"version": 1, "snapshots": history}
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return snapshot


def _std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / float(len(values))
    variance = sum((value - mean) ** 2 for value in values) / float(len(values))
    return float(variance ** 0.5)


def analyze_temporal_stability(
    history: list[dict[str, Any]] | None = None,
    *,
    window: int = 5,
) -> dict[str, Any]:
    snapshots = list(history if history is not None else load_analysis_history())
    recent = snapshots[-max(1, int(window)) :]
    if len(recent) < _STABILITY_MIN_SNAPSHOTS:
        return {
            "snapshots_used": len(recent),
            "min_snapshots": _STABILITY_MIN_SNAPSHOTS,
            "verdict": "insufficient_history",
            "stable_enough_for_review": False,
            "policy": _DIAGNOSTIC_POLICY,
        }

    overall_counts = Counter(str(item.get("overall_verdict") or "unknown") for item in recent)
    dominant_overall = overall_counts.most_common(1)[0][0]
    overall_agreement = overall_counts[dominant_overall] / float(len(recent))

    adaptive_counts = Counter(
        str(item.get("adaptive_vs_fixed_verdict") or "unknown") for item in recent
    )
    dominant_adaptive = adaptive_counts.most_common(1)[0][0]
    adaptive_agreement = adaptive_counts[dominant_adaptive] / float(len(recent))

    baseline_values = [
        float(item["baseline_mae_sec"])
        for item in recent
        if item.get("baseline_mae_sec") is not None
    ]
    baseline_std = _std(baseline_values)
    fragmentation_runs = sum(1 for item in recent if bool(item.get("fragmentation_warning")))

    dimension_agreement: dict[str, float] = {}
    for dimension in ("pace", "score_bucket", "confidence_band"):
        counts = Counter(
            str(item.get("dimension_verdicts", {}).get(dimension) or "unknown")
            for item in recent
        )
        if not counts:
            continue
        top = counts.most_common(1)[0]
        dimension_agreement[dimension] = top[1] / float(len(recent))

    stable_enough = (
        overall_agreement >= _STABILITY_AGREEMENT_RATIO
        and fragmentation_runs == 0
        and (baseline_std is None or baseline_std <= _STABILITY_BASELINE_MAE_STD_MAX)
    )
    verdict = "stable" if stable_enough else "unstable"

    return {
        "snapshots_used": len(recent),
        "min_snapshots": _STABILITY_MIN_SNAPSHOTS,
        "overall_verdict_mode": dominant_overall,
        "overall_agreement": overall_agreement,
        "adaptive_vs_fixed_mode": dominant_adaptive,
        "adaptive_vs_fixed_agreement": adaptive_agreement,
        "baseline_mae_std_sec": baseline_std,
        "fragmentation_runs": fragmentation_runs,
        "dimension_verdict_agreement": dimension_agreement,
        "stable_enough_for_review": stable_enough,
        "verdict": verdict,
        "policy": _DIAGNOSTIC_POLICY,
        "guidance": (
            "Even when stable, treat results as review input only; runtime auto-tune stays disabled by default."
        ),
    }


def evaluate_upgrade_gate(
    analysis: dict[str, Any],
    *,
    temporal_stability: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
    stability_window: int = 5,
) -> dict[str, Any]:
    """Minimal collapse-test gate: flag manual upgrade candidates only; never touch runtime."""
    stability = dict(temporal_stability or analysis.get("temporal_stability") or {})
    collapse = dict(analysis.get("segmentation_collapse") or {})
    snapshots = list(history if history is not None else load_analysis_history())
    recent = snapshots[-max(1, int(stability_window)) :]

    improved_dimensions = [
        str(row.get("dimension"))
        for row in (collapse.get("dimensions") or [])
        if str(row.get("verdict") or "") == "keep_segmentation"
        and row.get("improvement_sec") is not None
        and float(row["improvement_sec"]) >= EFFECT_SIZE_MIN_SEC
        and row.get("dimension")
    ]

    overall_mode = str(stability.get("overall_verdict_mode") or "")
    overall_agreement = float(stability.get("overall_agreement", 0.0) or 0.0)
    stable = bool(stability.get("stable_enough_for_review"))
    fragmentation_runs = int(stability.get("fragmentation_runs", 0) or 0)

    candidate_upgrade = False
    candidate_label = None
    status = "hold"
    rationale = "Collect more collapse-test history before marking an upgrade candidate."

    if len(recent) < _UPGRADE_MIN_CONFIRM_SNAPSHOTS:
        pass
    elif not stable or fragmentation_runs > 0:
        rationale = "Collapse signals are unstable or fragmented; do not version bump yet."
    elif overall_agreement < _UPGRADE_AGREEMENT_RATIO:
        rationale = "Collapse overall verdict is not consistent across recent runs."
    elif overall_mode == "prefer_merged_baseline":
        candidate_upgrade = True
        candidate_label = "prefer_merged_baseline"
        status = "candidate"
        rationale = "Collapse test is stable and consistently prefers merged baseline."
    elif improved_dimensions and overall_mode == "segmentation_partially_justified":
        candidate_upgrade = True
        candidate_label = f"keep_segmentation:{improved_dimensions[0]}"
        status = "candidate"
        rationale = (
            "Collapse test is stable with significant segmented improvement on "
            f"{improved_dimensions[0]}."
        )

    return {
        "status": status,
        "candidate_upgrade": candidate_upgrade,
        "candidate_label": candidate_label,
        "runtime_change": "none",
        "collapse_overall_mode": overall_mode or None,
        "collapse_overall_agreement": overall_agreement,
        "improved_dimensions": improved_dimensions,
        "recent_snapshots": len(recent),
        "min_confirm_snapshots": _UPGRADE_MIN_CONFIRM_SNAPSHOTS,
        "rationale": rationale,
        "policy": _UPGRADE_POLICY,
    }


def _window_sort_key(label: str) -> tuple[int, str]:
    try:
        return (0, f"{int(label):06d}")
    except (TypeError, ValueError):
        return (1, str(label))


def _recommend_window_policy(
    by_window: dict[str, dict[str, float | int]],
    by_score: dict[str, dict[str, float | int]],
    bucket_stats: dict[str, dict[str, float | int]],
) -> dict[str, Any]:
    reliable_windows: list[tuple[str, dict[str, float | int]]] = [
        (label, stats)
        for label, stats in by_window.items()
        if int(stats.get("samples", 0) or 0) >= MIN_RELIABLE_BUCKET_SAMPLES
    ]
    best_window = None
    if reliable_windows:
        best_label, best_stats = min(
            reliable_windows,
            key=lambda item: (_mean_error(item[1]) or float("inf")),
        )
        best_window = {
            "window_sec": best_label,
            "mean_error_sec": _mean_error(best_stats),
            "samples": int(best_stats.get("samples", 0) or 0),
        }

    baseline = by_window.get(str(int(_FIXED_BASELINE_WINDOW_SEC)))
    baseline_mean = _mean_error(baseline) if baseline else None
    adaptive_mean = None
    adaptive_samples = 0
    adaptive_error_sum = 0.0
    for key, stats in bucket_stats.items():
        parsed = parse_locate_bucket_key(key)
        if parsed.get("crop") == "1":
            continue
        try:
            window = int(parsed.get("window", "0"))
        except (TypeError, ValueError):
            continue
        if window == int(_FIXED_BASELINE_WINDOW_SEC):
            continue
        samples = int(stats.get("samples", 0) or 0)
        adaptive_samples += samples
        adaptive_error_sum += float(stats.get("error_sum_sec", 0.0) or 0.0)
    if adaptive_samples > 0:
        adaptive_mean = adaptive_error_sum / float(adaptive_samples)

    score_window_hints: list[dict[str, Any]] = []
    for score_label, stats in sorted(by_score.items()):
        if int(stats.get("samples", 0) or 0) < MIN_RELIABLE_BUCKET_SAMPLES:
            continue
        best_for_score = None
        best_error = float("inf")
        for key, bucket in bucket_stats.items():
            parsed = parse_locate_bucket_key(key)
            if parsed.get("score") != score_label or parsed.get("crop") == "1":
                continue
            samples = int(bucket.get("samples", 0) or 0)
            if samples < MIN_RELIABLE_BUCKET_SAMPLES:
                continue
            mean_error = _mean_error(bucket)
            if mean_error is None or mean_error >= best_error:
                continue
            best_error = mean_error
            best_for_score = parsed.get("window")
        if best_for_score is not None:
            score_window_hints.append(
                {
                    "score_bucket": score_label,
                    "best_window_sec": best_for_score,
                    "mean_error_sec": best_error,
                }
            )

    verdict = "insufficient_data"
    if baseline_mean is not None and adaptive_mean is not None:
        delta = float(adaptive_mean) - float(baseline_mean)
        if delta <= -EFFECT_SIZE_MIN_SEC:
            verdict = "adaptive_better_than_fixed_30s"
        elif delta >= EFFECT_SIZE_MIN_SEC:
            verdict = "fixed_30s_better_than_adaptive"
        else:
            verdict = "no_significant_difference"

    return {
        "min_samples_for_reliable_row": MIN_RELIABLE_BUCKET_SAMPLES,
        "effect_size_threshold_sec": EFFECT_SIZE_MIN_SEC,
        "advisory_only": True,
        "actionable": False,
        "best_window_overall": best_window,
        "fixed_30s": {
            "samples": int((baseline or {}).get("samples", 0) or 0),
            "mean_error_sec": baseline_mean,
        },
        "adaptive_non_30s": {
            "samples": adaptive_samples,
            "mean_error_sec": adaptive_mean,
        },
        "verdict": verdict,
        "score_window_hints": score_window_hints,
    }


def format_locate_window_report(analysis: dict[str, Any]) -> str:
    policy = dict(analysis.get("policy") or {})
    lines = [
        "Locate CLIP window effectiveness",
        f"policy={policy.get('mode', _DIAGNOSTIC_POLICY)} "
        f"runtime_decision_impact={policy.get('runtime_decision_impact', 'none')} "
        f"bias_auto_tune={'on' if policy.get('bias_auto_tune_enabled') else 'off'}",
        f"telemetry: {analysis.get('telemetry_path')} ({'found' if analysis.get('telemetry_exists') else 'missing'})",
        f"history: {analysis.get('analysis_history_path')}",
        f"total_samples={analysis.get('total_samples', 0)} bias={float(analysis.get('bias_sec', 0.0)):.0f}s",
    ]
    if policy.get("guidance"):
        lines.append(f"note: {policy.get('guidance')}")
    p50 = analysis.get("p50_anchor_error_sec")
    p90 = analysis.get("p90_anchor_error_sec")
    if p50 is not None or p90 is not None:
        lines.append(
            "anchor_error: "
            f"p50={p50 if p50 is not None else 'na'}s "
            f"p90={p90 if p90 is not None else 'na'}s"
        )

    lines.append("")
    lines.append("By window (non-crop):")
    for row in analysis.get("by_window") or []:
        mean_error = row.get("mean_error_sec")
        mean_text = "na" if mean_error is None else f"{float(mean_error):.2f}s"
        flag = "" if row.get("reliable") else " (low sample)"
        lines.append(
            f"  window={row.get('window_sec')}s samples={row.get('samples')} mean_error={mean_text}{flag}"
        )

    lines.append("")
    lines.append("By score bucket:")
    for row in analysis.get("by_score") or []:
        mean_error = row.get("mean_error_sec")
        mean_text = "na" if mean_error is None else f"{float(mean_error):.2f}s"
        flag = "" if row.get("reliable") else " (low sample)"
        lines.append(
            f"  score={row.get('score_bucket')} samples={row.get('samples')} mean_error={mean_text}{flag}"
        )

    lines.append("")
    lines.append("By margin bucket:")
    for row in analysis.get("by_margin") or []:
        mean_error = row.get("mean_error_sec")
        mean_text = "na" if mean_error is None else f"{float(mean_error):.2f}s"
        flag = "" if row.get("reliable") else " (low sample)"
        lines.append(
            f"  margin={row.get('margin_bucket')} samples={row.get('samples')} mean_error={mean_text}{flag}"
        )

    lines.append("")
    lines.append("By pace bucket:")
    for row in analysis.get("by_pace") or []:
        mean_error = row.get("mean_error_sec")
        mean_text = "na" if mean_error is None else f"{float(mean_error):.2f}s"
        flag = "" if row.get("reliable") else " (low sample)"
        lines.append(
            f"  pace={row.get('pace_bucket')} samples={row.get('samples')} mean_error={mean_text}{flag}"
        )

    lines.append("")
    lines.append("Window x pace:")
    for row in analysis.get("window_x_pace") or []:
        mean_error = row.get("mean_error_sec")
        mean_text = "na" if mean_error is None else f"{float(mean_error):.2f}s"
        flag = "" if row.get("reliable") else " (low sample)"
        lines.append(
            f"  window={row.get('window')}s pace={row.get('pace')} "
            f"samples={row.get('samples')} mean_error={mean_text}{flag}"
        )

    confidence = dict(analysis.get("confidence_analysis") or {})
    lines.append("")
    lines.append("Confidence validation:")
    lines.append(f"  samples={confidence.get('samples', 0)} verdict={confidence.get('verdict', 'insufficient_data')}")
    for key in ("correlation_error_score", "correlation_error_margin", "correlation_error_confidence"):
        value = confidence.get(key)
        text = "na" if value is None else f"{float(value):+.3f}"
        lines.append(f"  {key}={text}")
    if confidence.get("best_predictor"):
        lines.append(f"  best_predictor={confidence.get('best_predictor')}")

    collapse = dict(analysis.get("segmentation_collapse") or {})
    lines.append("")
    lines.append("Segmentation collapse test:")
    lines.append(
        f"  samples={collapse.get('samples', 0)} "
        f"overall={collapse.get('overall_verdict', 'insufficient_data')} "
        f"baseline_mae={collapse.get('baseline_mae_sec', 'na')}"
    )
    if collapse.get("fragmentation_warning"):
        lines.append(
            "  fragmentation_warning=yes (some buckets look good, overall/global does not)"
        )
    for row in collapse.get("dimensions") or []:
        improvement = row.get("improvement_sec")
        improvement_text = "na" if improvement is None else f"{float(improvement):+.2f}s"
        lines.append(
            f"  {row.get('dimension')}: verdict={row.get('verdict')} "
            f"improvement={improvement_text} sparse={row.get('sparse_groups') or []}"
        )

    stability = dict(analysis.get("temporal_stability") or {})
    lines.append("")
    lines.append("Temporal stability:")
    lines.append(
        f"  snapshots={stability.get('snapshots_used', 0)} "
        f"verdict={stability.get('verdict', 'insufficient_history')} "
        f"stable_for_review={'yes' if stability.get('stable_enough_for_review') else 'no'}"
    )
    if stability.get("overall_verdict_mode") is not None:
        lines.append(
            "  overall_mode="
            f"{stability.get('overall_verdict_mode')} "
            f"agreement={float(stability.get('overall_agreement', 0.0)):.0%}"
        )
    if stability.get("baseline_mae_std_sec") is not None:
        lines.append(f"  baseline_mae_std={float(stability['baseline_mae_std_sec']):.2f}s")
    if int(stability.get("fragmentation_runs", 0) or 0) > 0:
        lines.append(f"  fragmentation_runs={int(stability.get('fragmentation_runs', 0))}")

    bias_by_score = dict(analysis.get("bias_by_score") or {})
    if bias_by_score:
        lines.append("")
        lines.append("Segmented bias by score:")
        for score_label, bias_value in sorted(bias_by_score.items()):
            lines.append(f"  score={score_label} bias={float(bias_value):.0f}s")

    recommendation = dict(analysis.get("recommendation") or {})
    lines.append("")
    lines.append("Recommendation:")
    best = recommendation.get("best_window_overall")
    if best:
        lines.append(
            "  best_window="
            f"{best.get('window_sec')}s "
            f"mean_error={float(best.get('mean_error_sec')):.2f}s "
            f"samples={best.get('samples')}"
        )
    else:
        lines.append("  best_window=na (need more samples)")

    fixed = dict(recommendation.get("fixed_30s") or {})
    adaptive = dict(recommendation.get("adaptive_non_30s") or {})
    lines.append(
        "  fixed_30s: "
        f"samples={fixed.get('samples', 0)} "
        f"mean_error={fixed.get('mean_error_sec') if fixed.get('mean_error_sec') is not None else 'na'}"
    )
    lines.append(
        "  adaptive_non_30s: "
        f"samples={adaptive.get('samples', 0)} "
        f"mean_error={adaptive.get('mean_error_sec') if adaptive.get('mean_error_sec') is not None else 'na'}"
    )
    lines.append(f"  verdict={recommendation.get('verdict', 'insufficient_data')} (advisory only)")

    hints = recommendation.get("score_window_hints") or []
    if hints:
        lines.append("")
        lines.append("Score bucket hints:")
        for hint in hints:
            lines.append(
                "  score="
                f"{hint.get('score_bucket')} -> window={hint.get('best_window_sec')}s "
                f"mean_error={float(hint.get('mean_error_sec')):.2f}s"
            )

    upgrade = dict(analysis.get("upgrade_gate") or {})
    lines.append("")
    lines.append("Upgrade gate (collapse test only, manual version control):")
    lines.append(
        f"  status={upgrade.get('status', 'hold')} "
        f"candidate={upgrade.get('candidate_upgrade', False)} "
        f"runtime_change={upgrade.get('runtime_change', 'none')}"
    )
    if upgrade.get("candidate_label"):
        lines.append(f"  candidate_label={upgrade.get('candidate_label')}")
    if upgrade.get("rationale"):
        lines.append(f"  rationale: {upgrade.get('rationale')}")

    return "\n".join(lines)


def format_version_decision_report(analysis: dict[str, Any]) -> str:
    """One-page template for manual runtime version decisions; does not change runtime."""
    from datetime import datetime, timezone

    policy = dict(analysis.get("policy") or {})
    collapse = dict(analysis.get("segmentation_collapse") or {})
    stability = dict(analysis.get("temporal_stability") or {})
    upgrade = dict(analysis.get("upgrade_gate") or {})
    recommendation = dict(analysis.get("recommendation") or {})

    candidate = bool(upgrade.get("candidate_upgrade"))
    decision_action = "REVIEW_CANDIDATE" if candidate else "HOLD_CURRENT_RUNTIME"

    p50 = analysis.get("p50_anchor_error_sec")
    p90 = analysis.get("p90_anchor_error_sec")
    lines = [
        "Locate Policy Version Decision Report",
        f"generated_at={datetime.now(timezone.utc).isoformat()}",
        "",
        "== Summary ==",
        f"decision_action={decision_action}",
        f"candidate_upgrade={str(candidate).lower()}",
        f"candidate_label={upgrade.get('candidate_label') or 'none'}",
        f"runtime_change={upgrade.get('runtime_change', 'none')}",
        f"policy={policy.get('mode', _DIAGNOSTIC_POLICY)}",
        "",
        "== Telemetry ==",
        f"total_locate_samples={analysis.get('total_samples', 0)}",
        f"anchor_error_p50={p50 if p50 is not None else 'na'}s",
        f"anchor_error_p90={p90 if p90 is not None else 'na'}s",
        f"telemetry={analysis.get('telemetry_path')}",
        "",
        "== Collapse test (current) ==",
        f"overall={collapse.get('overall_verdict', 'insufficient_data')}",
        f"baseline_mae={collapse.get('baseline_mae_sec', 'na')}",
        f"fragmentation_warning={str(bool(collapse.get('fragmentation_warning'))).lower()}",
    ]
    for row in collapse.get("dimensions") or []:
        improvement = row.get("improvement_sec")
        improvement_text = "na" if improvement is None else f"{float(improvement):+.2f}s"
        lines.append(
            f"  {row.get('dimension')}: {row.get('verdict')} improvement={improvement_text}"
        )

    lines.extend(
        [
            "",
            "== Stability (recent history) ==",
            f"snapshots={stability.get('snapshots_used', 0)}",
            f"verdict={stability.get('verdict', 'insufficient_history')}",
            f"collapse_mode={stability.get('overall_verdict_mode', 'na')}",
            f"collapse_agreement={float(stability.get('overall_agreement', 0.0)):.0%}",
            f"fragmentation_runs={int(stability.get('fragmentation_runs', 0) or 0)}",
            "",
            "== Adaptive vs fixed 30s (advisory) ==",
            f"verdict={recommendation.get('verdict', 'insufficient_data')}",
            "",
            "== Upgrade gate ==",
            f"status={upgrade.get('status', 'hold')}",
            f"rationale={upgrade.get('rationale', '')}",
            "",
            "== Manual checklist ==",
            "[ ] collapse stable across >= 5 snapshots",
            "[ ] significant improvement >= effect size threshold",
            "[ ] no fragmentation in recent history",
            "[ ] candidate_upgrade=true in this report",
            "[ ] runtime change planned as explicit git release (not auto-tune)",
            "",
            "== Decision ==",
            f"action={decision_action}",
            "note=Analysis is offline diagnostics only; runtime stays unchanged until you ship a version.",
        ]
    )
    return "\n".join(lines)


def load_and_analyze_locate_window_stats(
    *,
    reload: bool = False,
    record_history: bool = True,
    stability_window: int = 5,
) -> dict[str, Any]:
    if reload:
        reload_telemetry_state()
    analysis = analyze_locate_window_stats()
    if record_history:
        record_analysis_snapshot(analysis)
    analysis["temporal_stability"] = analyze_temporal_stability(window=stability_window)
    analysis["upgrade_gate"] = evaluate_upgrade_gate(
        analysis,
        temporal_stability=analysis["temporal_stability"],
        stability_window=stability_window,
    )
    return analysis
