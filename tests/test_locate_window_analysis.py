import pytest

from src.services.locate_window_analysis import (
    analyze_locate_window_stats,
    format_locate_window_report,
    format_version_decision_report,
    parse_locate_bucket_key,
)


def test_parse_locate_bucket_key():
    parsed = parse_locate_bucket_key("score=0.8|margin=0.05|window=20|crop=0")
    assert parsed == {
        "score": "0.8",
        "margin": "0.05",
        "window": "20",
        "crop": "0",
    }


def test_analyze_locate_window_stats_aggregates_dimensions():
    summary = {
        "locate_clip_window": {
            "samples": 12,
            "bias_sec": 5.0,
            "p50_anchor_error_sec": 2.0,
            "p90_anchor_error_sec": 4.0,
            "bucket_stats": {
                "score=0.8|margin=0.10+|window=10|pace=fast_cut|crop=0": {"samples": 5, "error_sum_sec": 5.0},
                "score=0.7|margin=0.05|window=20|pace=normal|crop=0": {"samples": 5, "error_sum_sec": 20.0},
                "score=0.6|margin=<0.05|window=40|pace=stable|crop=0": {"samples": 2, "error_sum_sec": 8.0},
                "score=0.8|margin=0.10+|window=5|pace=fast_cut|crop=1": {"samples": 99, "error_sum_sec": 999.0},
            },
        }
    }

    analysis = analyze_locate_window_stats(summary)
    assert analysis["total_samples"] == 12
    assert analysis["by_window"][0]["window_sec"] == "10"
    assert analysis["by_window"][0]["mean_error_sec"] == pytest.approx(1.0)
    assert analysis["recommendation"]["best_window_overall"] is None
    assert analysis["by_pace"]
    assert analysis["window_x_pace"]
    assert analysis["segmentation_collapse"]["overall_verdict"] == "insufficient_data"


def test_format_locate_window_report_contains_sections():
    analysis = analyze_locate_window_stats(
        {
            "locate_clip_window": {
                "samples": 5,
                "bias_sec": 0.0,
                "bucket_stats": {
                    "score=0.8|margin=0.10+|window=10|pace=normal|crop=0": {"samples": 5, "error_sum_sec": 5.0},
                },
            }
        }
    )
    text = format_locate_window_report(analysis)
    assert "By window" in text
    assert "By score bucket" in text
    assert "Segmentation collapse test" in text
    assert "Temporal stability" in text
    assert "Upgrade gate" in text
    assert "advisory only" in text


def test_format_version_decision_report_is_concise():
    analysis = analyze_locate_window_stats(
        {
            "locate_clip_window": {
                "samples": 40,
                "bias_sec": 0.0,
                "bucket_stats": {},
            }
        }
    )
    analysis["temporal_stability"] = {
        "snapshots_used": 0,
        "verdict": "insufficient_history",
        "fragmentation_runs": 0,
    }
    analysis["upgrade_gate"] = {
        "status": "hold",
        "candidate_upgrade": False,
        "runtime_change": "none",
        "rationale": "Collect more history.",
    }
    text = format_version_decision_report(analysis)
    assert "Version Decision Report" in text
    assert "decision_action=HOLD_CURRENT_RUNTIME" in text
    assert "Manual checklist" in text
    assert "runtime stays unchanged" in text
