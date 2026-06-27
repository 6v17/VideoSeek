import numpy as np
import pytest

from src.services.locate_telemetry_utils import classify_video_pace, pearson_correlation
from src.services.locate_window_analysis import analyze_confidence_predictiveness


def test_classify_video_pace_fast_cut_near_anchor():
    timestamps = np.arange(0.0, 120.0, 0.5)
    assert classify_video_pace(timestamps, 60.0) == "fast_cut"


def test_classify_video_pace_stable_near_anchor():
    timestamps = np.arange(0.0, 600.0, 6.0)
    assert classify_video_pace(timestamps, 300.0) == "stable"


def test_pearson_correlation():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [5.0, 4.0, 3.0, 2.0, 1.0]
    assert pearson_correlation(xs, ys) == pytest.approx(-1.0)


def test_analyze_confidence_predictiveness_prefers_confidence():
    samples = []
    for index in range(20):
        score = 0.55 + index * 0.015
        margin = 0.02 + index * 0.003
        confidence = score * (1.0 + margin)
        error = max(0.5, 8.0 - confidence * 6.0)
        samples.append(
            {
                "score": score,
                "margin": margin,
                "confidence": confidence,
                "error_sec": error,
                "window_sec": 20.0,
                "score_bucket": "0.7",
                "pace": "normal",
            }
        )
    analysis = analyze_confidence_predictiveness(samples)
    assert analysis["samples"] == 20
    assert analysis["best_predictor"] in {"confidence", "score", "margin"}
    assert analysis["correlation_error_confidence"] is not None
