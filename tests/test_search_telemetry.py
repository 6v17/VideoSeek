import json

import pytest

import src.services.search_telemetry as telemetry


@pytest.fixture(autouse=True)
def reset_telemetry_state(monkeypatch, tmp_path):
    telemetry_file = tmp_path / "search_telemetry.json"
    monkeypatch.setattr(telemetry, "get_telemetry_file_path", lambda: str(telemetry_file))
    monkeypatch.setattr(telemetry, "is_telemetry_enabled", lambda config=None: True)
    with telemetry._lock:
        telemetry._state = None
        telemetry._pending_playback = None
    yield
    with telemetry._lock:
        telemetry._state = None
        telemetry._pending_playback = None


def test_record_crop_locate_anchor_updates_summary():
    telemetry.record_crop_locate_anchor(
        anchor_sec=64.0,
        result_sec=64.0,
        anchor_kept=True,
        best_sec=67.0,
        best_score=0.94,
        anchor_score=0.91,
        clip_score=0.91,
        video_path=r"D:\videos\demo.mp4",
    )
    telemetry.record_crop_locate_anchor(
        anchor_sec=120.0,
        result_sec=125.0,
        anchor_kept=False,
        best_sec=125.0,
        best_score=0.82,
        anchor_score=0.70,
        clip_score=0.82,
        video_path=r"D:\videos\demo.mp4",
    )

    summary = telemetry.get_telemetry_summary()
    crop = summary["crop_locate"]
    assert crop["total"] == 2
    assert crop["anchor_kept"] == 1
    assert crop["anchor_moved"] == 1
    assert crop["retention_rate"] == pytest.approx(0.5)


def test_record_crop_confidence_tracks_source_and_tier():
    telemetry.record_crop_confidence(
        score=0.88,
        tier_key="clip_confidence_very_high",
        source="crop_locate",
    )
    telemetry.record_crop_confidence(
        score=0.55,
        tier_key="clip_confidence_low",
        source="crop_search",
    )

    summary = telemetry.get_telemetry_summary()
    assert summary["confidence_tiers"]["clip_confidence_very_high"] == 1
    assert summary["confidence_tiers"]["clip_confidence_low"] == 1
    assert summary["confidence_by_source"]["crop_locate"]["clip_confidence_very_high"] == 1
    assert summary["confidence_by_source"]["crop_search"]["clip_confidence_low"] == 1


def test_playback_session_records_delta():
    telemetry.begin_playback_session(video_path=r"D:\videos\demo.mp4", suggested_sec=64.0, playback_start_sec=61.0)
    telemetry.mark_playback_user_adjusted()
    telemetry.finish_playback_session(actual_sec=65.0, source="inline")

    summary = telemetry.get_telemetry_summary()
    playback = summary["playback_bias"]
    assert playback["samples"] == 1
    assert playback["mean_abs_delta_sec"] == pytest.approx(1.0)
    assert playback["within_1s"] == 1
    assert playback["within_5s"] == 1
    assert playback["p50_abs_delta_sec"] == pytest.approx(1.0)


def test_playback_passive_watch_is_not_recorded():
    telemetry.begin_playback_session(video_path=r"D:\videos\demo.mp4", suggested_sec=64.0, playback_start_sec=61.0)
    telemetry.finish_playback_session(actual_sec=67.0, source="inline")

    summary = telemetry.get_telemetry_summary()
    playback = summary["playback_bias"]
    assert playback["samples"] == 0
    assert playback["passive_skipped"] == 1


def test_playback_percentiles_with_multiple_samples():
    for actual in (64.0, 65.0, 70.0, 72.0, 81.0):
        telemetry.begin_playback_session(video_path=r"D:\videos\demo.mp4", suggested_sec=64.0, playback_start_sec=61.0)
        telemetry.mark_playback_user_adjusted()
        telemetry.finish_playback_session(actual_sec=actual, source="inline")

    summary = telemetry.get_telemetry_summary()
    playback = summary["playback_bias"]
    assert playback["samples"] == 5
    assert playback["p50_abs_delta_sec"] == pytest.approx(6.0)
    assert playback["p90_abs_delta_sec"] == pytest.approx(13.4)
    assert playback["p95_abs_delta_sec"] == pytest.approx(15.2)


def test_format_telemetry_panel_uses_localized_labels():
    telemetry.record_crop_locate_anchor(
        anchor_sec=10.0,
        result_sec=10.0,
        anchor_kept=True,
        clip_score=0.9,
    )
    telemetry.record_crop_confidence(
        score=0.88,
        tier_key="clip_confidence_very_high",
        source="crop_locate",
    )
    telemetry.begin_playback_session(video_path=r"D:\videos\demo.mp4", suggested_sec=64.0, playback_start_sec=61.0)
    telemetry.mark_playback_user_adjusted()
    telemetry.finish_playback_session(actual_sec=65.0, source="inline")

    texts = {
        "search_telemetry_panel_anchor_retention": "Anchor 保留率",
        "search_telemetry_panel_playback_mean": "播放平均绝对偏差",
        "search_telemetry_panel_playback_within_1s": "播放 ±1s 内",
        "search_telemetry_panel_confidence": "置信度分布",
        "clip_confidence_very_high": "很高",
        "search_telemetry_panel_samples": "样本：定位={locate} 播放={playback} 置信度={confidence}",
    }
    panel = telemetry.format_telemetry_panel(language="zh", texts=texts)
    assert "Anchor 保留率" in panel
    assert "100.0%" in panel
    assert "很高" in panel


def test_playback_session_without_begin_is_ignored():
    telemetry.finish_playback_session(actual_sec=65.0, source="inline")
    summary = telemetry.get_telemetry_summary()
    assert summary["playback_bias"]["samples"] == 0


def test_persistence_round_trip(tmp_path):
    telemetry.record_crop_locate_anchor(
        anchor_sec=10.0,
        result_sec=10.0,
        anchor_kept=True,
        clip_score=0.8,
    )

    with telemetry._lock:
        telemetry._state = None

    reloaded = telemetry.get_telemetry_summary()
    assert reloaded["crop_locate"]["total"] == 1
    assert reloaded["crop_locate"]["anchor_kept"] == 1

    payload = json.loads((tmp_path / "search_telemetry.json").read_text(encoding="utf-8"))
    assert payload["version"] == 5
    assert payload["crop_locate"]["total"] == 1


def test_format_telemetry_summary_contains_key_sections():
    telemetry.record_crop_locate_anchor(
        anchor_sec=1.0,
        result_sec=1.0,
        anchor_kept=True,
        clip_score=0.9,
    )
    text = telemetry.format_telemetry_summary(language="zh")
    assert "截图定位 anchor 保留" in text
    assert "置信度分布" in text
    assert "播放偏差" in text


def test_locate_bias_auto_tune_disabled_by_default():
    assert telemetry.is_locate_bias_auto_tune_enabled() is False
    assert telemetry.get_locate_clip_window_bias_sec(score=0.78) == 0.0


def test_record_locate_clip_window_does_not_apply_segmented_bias_without_gating(monkeypatch):
    monkeypatch.setattr(telemetry, "_LOCATE_CLIP_BIAS_SEGMENT_INTERVAL", 2)
    monkeypatch.setattr(telemetry, "_LOCATE_CLIP_BIAS_SEGMENT_MIN_ERRORS", 2)
    telemetry.record_locate_clip_window(
        window_sec=20.0,
        score=0.78,
        margin=0.08,
        anchor_sec=64.0,
        result_sec=67.0,
        is_crop=False,
        confidence=0.8424,
        video_pace="normal",
    )
    telemetry.record_locate_clip_window(
        window_sec=20.0,
        score=0.78,
        margin=0.08,
        anchor_sec=120.0,
        result_sec=126.0,
        is_crop=False,
        confidence=0.8424,
        video_pace="normal",
    )

    summary = telemetry.get_telemetry_summary()
    locate = summary["locate_clip_window"]
    assert locate["samples"] == 2
    assert "0.7" not in locate.get("bias_by_score", {})
    assert telemetry.get_locate_clip_window_bias_sec(score=0.78) == pytest.approx(0.0)
