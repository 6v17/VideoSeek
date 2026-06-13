from src.services.locate_segmentation_gating import EFFECT_SIZE_MIN_SEC
from src.services.locate_window_analysis import evaluate_upgrade_gate


def _stability(**overrides) -> dict:
    base = {
        "stable_enough_for_review": True,
        "overall_verdict_mode": "prefer_merged_baseline",
        "overall_agreement": 0.8,
        "fragmentation_runs": 0,
    }
    base.update(overrides)
    return base


def test_upgrade_gate_holds_without_enough_snapshots():
    result = evaluate_upgrade_gate(
        {"segmentation_collapse": {"dimensions": []}},
        temporal_stability=_stability(),
        history=[{"overall_verdict": "prefer_merged_baseline"}] * 2,
    )
    assert result["status"] == "hold"
    assert result["candidate_upgrade"] is False
    assert result["runtime_change"] == "none"


def test_upgrade_gate_marks_stable_merged_baseline_candidate():
    history = [{"overall_verdict": "prefer_merged_baseline"} for _ in range(5)]
    result = evaluate_upgrade_gate(
        {"segmentation_collapse": {"dimensions": [], "overall_verdict": "prefer_merged_baseline"}},
        temporal_stability=_stability(),
        history=history,
    )
    assert result["status"] == "candidate"
    assert result["candidate_upgrade"] is True
    assert result["candidate_label"] == "prefer_merged_baseline"
    assert result["runtime_change"] == "none"


def test_upgrade_gate_marks_segmentation_improvement_candidate():
    history = [{"overall_verdict": "segmentation_partially_justified"} for _ in range(5)]
    result = evaluate_upgrade_gate(
        {
            "segmentation_collapse": {
                "overall_verdict": "segmentation_partially_justified",
                "dimensions": [
                    {
                        "dimension": "pace",
                        "verdict": "keep_segmentation",
                        "improvement_sec": EFFECT_SIZE_MIN_SEC + 0.5,
                    }
                ],
            }
        },
        temporal_stability=_stability(overall_verdict_mode="segmentation_partially_justified"),
        history=history,
    )
    assert result["status"] == "candidate"
    assert result["candidate_label"] == "keep_segmentation:pace"
