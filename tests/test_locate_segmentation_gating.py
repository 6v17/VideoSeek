import pytest

from src.services.locate_segmentation_gating import (
    EFFECT_SIZE_MIN_SEC,
    MIN_RELIABLE_BUCKET_SAMPLES,
    analyze_dimension_collapse,
    merged_baseline_mae,
    passes_effect_size_gate,
)
from src.services.locate_window_analysis import (
    analyze_segmentation_collapse_test,
    analyze_temporal_stability,
)


def _make_samples(
    *,
    count: int,
    pace: str,
    score_bucket: str,
    error_sec: float,
    confidence: float,
) -> list[dict]:
    return [
        {
            "score": 0.78,
            "margin": 0.08,
            "confidence": confidence,
            "error_sec": error_sec,
            "window_sec": 20.0,
            "score_bucket": score_bucket,
            "pace": pace,
        }
        for _ in range(count)
    ]


def test_passes_effect_size_gate_requires_meaningful_delta():
    assert passes_effect_size_gate(
        segment_mean=4.0,
        global_mean=2.0,
        segment_p90=5.0,
        global_p90=2.5,
    )
    assert not passes_effect_size_gate(
        segment_mean=2.1,
        global_mean=2.0,
        segment_p90=2.4,
        global_p90=2.3,
    )


def test_analyze_dimension_collapse_prefers_merged_when_sparse():
    samples = _make_samples(count=8, pace="fast_cut", score_bucket="0.7", error_sec=2.0, confidence=0.8)
    samples.extend(_make_samples(count=8, pace="stable", score_bucket="0.7", error_sec=2.5, confidence=0.8))
    result = analyze_dimension_collapse(
        samples,
        dimension="pace",
        group_key=lambda sample: str(sample["pace"]),
    )
    assert result["verdict"] == "insufficient_data" or result["verdict"] == "collapse_sparse_buckets"


def test_analyze_segmentation_collapse_test_detects_useful_pace_split():
    stable = _make_samples(count=20, pace="stable", score_bucket="0.7", error_sec=1.0, confidence=0.84)
    fast = _make_samples(count=20, pace="fast_cut", score_bucket="0.7", error_sec=4.0, confidence=0.84)
    samples = stable + fast
    assert merged_baseline_mae(samples) is not None
    result = analyze_segmentation_collapse_test(samples)
    pace_row = next(row for row in result["dimensions"] if row["dimension"] == "pace")
    assert pace_row["improvement_sec"] is not None
    assert pace_row["improvement_sec"] >= EFFECT_SIZE_MIN_SEC
    assert pace_row["verdict"] == "keep_segmentation"
    assert result["overall_verdict"] == "segmentation_partially_justified"
    assert result["fragmentation_warning"] is True


def test_analyze_segmentation_collapse_test_insufficient_without_samples():
    result = analyze_segmentation_collapse_test(
        _make_samples(count=5, pace="normal", score_bucket="0.7", error_sec=2.0, confidence=0.8)
    )
    assert result["overall_verdict"] == "insufficient_data"
    assert result["samples"] < MIN_RELIABLE_BUCKET_SAMPLES


def test_analyze_temporal_stability_requires_history():
    history = [
        {
            "overall_verdict": "prefer_merged_baseline",
            "adaptive_vs_fixed_verdict": "no_significant_difference",
            "baseline_mae_sec": 2.0,
            "fragmentation_warning": False,
            "dimension_verdicts": {"pace": "collapse_no_effect"},
        }
        for _ in range(3)
    ]
    result = analyze_temporal_stability(history, window=3)
    assert result["verdict"] == "stable"
    assert result["stable_enough_for_review"] is True


def test_analyze_temporal_stability_flags_fragmentation_runs():
    history = [
        {
            "overall_verdict": "prefer_merged_baseline",
            "adaptive_vs_fixed_verdict": "no_significant_difference",
            "baseline_mae_sec": 2.0,
            "fragmentation_warning": True,
            "dimension_verdicts": {"pace": "keep_segmentation"},
        }
        for _ in range(3)
    ]
    result = analyze_temporal_stability(history, window=3)
    assert result["stable_enough_for_review"] is False
    assert result["fragmentation_runs"] == 3
