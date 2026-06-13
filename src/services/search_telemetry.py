from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.app.config import DEFAULT_CONFIG
from src.app.logging_utils import get_app_data_dir, get_logger

from src.services.locate_segmentation_gating import (
    MIN_BIAS_SEGMENT_BUCKET_SAMPLES,
    MIN_BIAS_SEGMENT_ERRORS,
    MIN_RELIABLE_BUCKET_SAMPLES,
    P90_EFFECT_SIZE_MIN_SEC,
    passes_effect_size_gate,
)

logger = get_logger("search_telemetry")

_TELEMETRY_VERSION = 5
_SUMMARY_LOG_INTERVAL = 10
_PLAYBACK_DELTA_SAMPLE_CAP = 5000
_LOCATE_CLIP_ERROR_SAMPLE_CAP = 5000
_LOCATE_CLIP_SIGNAL_SAMPLE_CAP = 5000
_LOCATE_CLIP_ADJUST_INTERVAL = 1000
_LOCATE_CLIP_BIAS_SEGMENT_INTERVAL = 50
_LOCATE_CLIP_BIAS_SEGMENT_MIN_ERRORS = MIN_BIAS_SEGMENT_ERRORS
_LOCATE_CLIP_P90_HIGH_SEC = 3.0
_LOCATE_CLIP_P90_LOW_SEC = 1.0
_LOCATE_CLIP_BIAS_STEP_SEC = 5.0
_LOCATE_CLIP_BIAS_MAX_SEC = 15.0

_TIER_ORDER = (
    "clip_confidence_very_high",
    "clip_confidence_high",
    "clip_confidence_medium",
    "clip_confidence_low",
)

_lock = threading.Lock()
_state: "SearchTelemetryState | None" = None
_pending_playback: dict[str, Any] | None = None


@dataclass
class SearchTelemetryState:
    crop_locate_total: int = 0
    crop_locate_anchor_kept: int = 0
    crop_locate_anchor_moved: int = 0
    confidence_tiers: dict[str, int] = field(default_factory=dict)
    confidence_by_source: dict[str, dict[str, int]] = field(default_factory=dict)
    playback_samples: int = 0
    playback_abs_delta_sum_sec: float = 0.0
    playback_within_1s: int = 0
    playback_within_5s: int = 0
    playback_abs_delta_samples: list[float] = field(default_factory=list)
    playback_passive_skipped: int = 0
    locate_clip_bias_sec: float = 0.0
    locate_clip_bias_by_score: dict[str, float] = field(default_factory=dict)
    locate_clip_samples: int = 0
    locate_clip_error_samples: list[float] = field(default_factory=list)
    locate_clip_signal_samples: list[dict[str, float | str]] = field(default_factory=list)
    locate_clip_bucket_stats: dict[str, dict[str, float | int]] = field(default_factory=dict)
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": _TELEMETRY_VERSION,
            "updated_at": self.updated_at,
            "crop_locate": {
                "total": self.crop_locate_total,
                "anchor_kept": self.crop_locate_anchor_kept,
                "anchor_moved": self.crop_locate_anchor_moved,
                "retention_rate": _ratio(self.crop_locate_anchor_kept, self.crop_locate_total),
            },
            "confidence_tiers": dict(self.confidence_tiers),
            "confidence_by_source": {
                source: dict(tiers) for source, tiers in self.confidence_by_source.items()
            },
            "playback_bias": {
                "samples": self.playback_samples,
                "passive_skipped": self.playback_passive_skipped,
                "abs_delta_sum_sec": self.playback_abs_delta_sum_sec,
                "mean_abs_delta_sec": _mean(self.playback_abs_delta_sum_sec, self.playback_samples),
                "within_1s": self.playback_within_1s,
                "within_5s": self.playback_within_5s,
                "within_1s_rate": _ratio(self.playback_within_1s, self.playback_samples),
                "within_5s_rate": _ratio(self.playback_within_5s, self.playback_samples),
                "p50_abs_delta_sec": _percentile(self.playback_abs_delta_samples, 50),
                "p90_abs_delta_sec": _percentile(self.playback_abs_delta_samples, 90),
                "p95_abs_delta_sec": _percentile(self.playback_abs_delta_samples, 95),
                "requires_user_adjustment": True,
            },
            "locate_clip_window": {
                "samples": self.locate_clip_samples,
                "bias_sec": self.locate_clip_bias_sec,
                "bias_by_score": dict(self.locate_clip_bias_by_score),
                "p50_anchor_error_sec": _percentile(self.locate_clip_error_samples, 50),
                "p90_anchor_error_sec": _percentile(self.locate_clip_error_samples, 90),
                "bucket_stats": {
                    key: dict(stats) for key, stats in self.locate_clip_bucket_stats.items()
                },
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SearchTelemetryState":
        crop = dict(payload.get("crop_locate") or {})
        playback = dict(payload.get("playback_bias") or {})
        locate_clip = dict(payload.get("locate_clip_window") or {})
        by_source = dict(payload.get("confidence_by_source") or {})
        bucket_stats = dict(locate_clip.get("bucket_stats") or {})
        return cls(
            crop_locate_total=int(crop.get("total", 0) or 0),
            crop_locate_anchor_kept=int(crop.get("anchor_kept", 0) or 0),
            crop_locate_anchor_moved=int(crop.get("anchor_moved", 0) or 0),
            confidence_tiers={str(k): int(v or 0) for k, v in dict(payload.get("confidence_tiers") or {}).items()},
            confidence_by_source={
                str(source): {str(k): int(v or 0) for k, v in dict(tiers or {}).items()}
                for source, tiers in by_source.items()
            },
            playback_samples=int(playback.get("samples", 0) or 0),
            playback_abs_delta_sum_sec=float(playback.get("abs_delta_sum_sec", 0.0) or 0.0),
            playback_within_1s=int(playback.get("within_1s", 0) or 0),
            playback_within_5s=int(playback.get("within_5s", 0) or 0),
            playback_abs_delta_samples=_normalize_delta_samples(playback.get("abs_delta_samples")),
            playback_passive_skipped=int(playback.get("passive_skipped", 0) or 0),
            locate_clip_bias_sec=float(locate_clip.get("bias_sec", 0.0) or 0.0),
            locate_clip_bias_by_score={
                str(k): float(v or 0.0)
                for k, v in dict(locate_clip.get("bias_by_score") or {}).items()
            },
            locate_clip_samples=int(locate_clip.get("samples", 0) or 0),
            locate_clip_error_samples=_normalize_delta_samples(locate_clip.get("error_samples")),
            locate_clip_signal_samples=_normalize_signal_samples(locate_clip.get("signal_samples")),
            locate_clip_bucket_stats={
                str(key): {
                    "samples": int((stats or {}).get("samples", 0) or 0),
                    "error_sum_sec": float((stats or {}).get("error_sum_sec", 0.0) or 0.0),
                }
                for key, stats in bucket_stats.items()
            },
            updated_at=str(payload.get("updated_at") or ""),
        )


def is_telemetry_enabled(config=None) -> bool:
    from src.app.config import load_config

    cfg = config or load_config()
    return bool(cfg.get("search_telemetry_enabled", DEFAULT_CONFIG.get("search_telemetry_enabled", True)))


def is_locate_bias_auto_tune_enabled(config=None) -> bool:
    from src.app.config import load_config

    cfg = config or load_config()
    return bool(
        cfg.get(
            "locate_clip_bias_auto_tune_enabled",
            DEFAULT_CONFIG.get("locate_clip_bias_auto_tune_enabled", False),
        )
    )


def get_telemetry_file_path() -> str:
    return os.path.join(get_app_data_dir(), "telemetry", "search_telemetry.json")


def get_locate_signal_samples() -> list[dict[str, float | str]]:
    with _lock:
        state = _ensure_state_locked()
        return list(state.locate_clip_signal_samples)


def get_telemetry_summary() -> dict[str, Any]:
    with _lock:
        state = _ensure_state_locked()
        return state.to_dict()


def reload_telemetry_state() -> dict[str, Any]:
    global _state
    with _lock:
        _state = _load_state()
        return _state.to_dict()


def format_telemetry_panel(*, language: str = "zh", texts: dict[str, Any] | None = None) -> str:
    if not is_telemetry_enabled():
        labels = texts or {}
        if language == "en":
            return str(labels.get("search_telemetry_disabled", "Screenshot search telemetry is disabled."))
        return str(labels.get("search_telemetry_disabled", "截图搜索遥测已关闭。"))

    summary = get_telemetry_summary()
    crop = summary.get("crop_locate") or {}
    playback = summary.get("playback_bias") or {}
    tiers = summary.get("confidence_tiers") or {}
    labels = texts or {}
    total_tiers = sum(int(v or 0) for v in tiers.values())
    na = "—"

    def pct_rate(value: float | int | None) -> str:
        if value is None:
            return na
        return f"{float(value) * 100.0:.1f}%"

    def pct_share(count: int) -> str:
        if total_tiers <= 0:
            return na
        return f"{int(count) * 100.0 / float(total_tiers):.1f}%"

    def sec_value(value: float | None) -> str:
        if value is None:
            return na
        return f"{float(value):.1f}s"

    if language == "en":
        lines = [
            str(labels.get("search_telemetry_panel_anchor_retention", "Anchor retention")),
            pct_rate(crop.get("retention_rate")),
            "",
            str(labels.get("search_telemetry_panel_playback_mean", "Playback mean abs delta")),
            sec_value(playback.get("mean_abs_delta_sec") if int(playback.get("samples", 0) or 0) > 0 else None),
            "",
            str(labels.get("search_telemetry_panel_playback_within_1s", "Playback within 1s")),
            pct_rate(playback.get("within_1s_rate") if int(playback.get("samples", 0) or 0) > 0 else None),
        ]
        playback_note = str(labels.get("search_telemetry_panel_playback_note", "") or "").strip()
        if playback_note:
            lines.extend(["", playback_note])
        if int(playback.get("samples", 0) or 0) < 30:
            low_sample = str(labels.get("search_telemetry_panel_low_sample_note", "") or "").strip()
            if low_sample:
                lines.extend(["", low_sample])
        if int(playback.get("samples", 0) or 0) >= 5:
            lines.extend(
                [
                    "",
                    str(labels.get("search_telemetry_panel_playback_percentiles", "Playback abs delta percentiles")),
                    f"p50 = {sec_value(playback.get('p50_abs_delta_sec'))}",
                    f"p90 = {sec_value(playback.get('p90_abs_delta_sec'))}",
                    f"p95 = {sec_value(playback.get('p95_abs_delta_sec'))}",
                ]
            )
        lines.extend(["", str(labels.get("search_telemetry_panel_confidence", "Confidence"))])
        for tier_key in _TIER_ORDER:
            count = int(tiers.get(tier_key, 0) or 0)
            if total_tiers <= 0 and count <= 0:
                continue
            tier_label = str(labels.get(tier_key, tier_key))
            lines.append(f"{tier_label:<10} {pct_share(count)}")
        lines.extend(
            [
                "",
                str(
                    labels.get(
                        "search_telemetry_panel_samples",
                        "Samples: locate={locate} playback={playback} confidence={confidence}",
                    ).format(
                        locate=int(crop.get("total", 0) or 0),
                        playback=int(playback.get("samples", 0) or 0),
                        confidence=total_tiers,
                    )
                ),
            ]
        )
        return "\n".join(lines)

    lines = [
        str(labels.get("search_telemetry_panel_anchor_retention", "Anchor 保留率")),
        pct_rate(crop.get("retention_rate")),
        "",
        str(labels.get("search_telemetry_panel_playback_mean", "播放平均绝对偏差")),
        sec_value(playback.get("mean_abs_delta_sec") if int(playback.get("samples", 0) or 0) > 0 else None),
        "",
        str(labels.get("search_telemetry_panel_playback_within_1s", "播放 ±1s 内")),
        pct_rate(playback.get("within_1s_rate") if int(playback.get("samples", 0) or 0) > 0 else None),
    ]
    playback_note = str(labels.get("search_telemetry_panel_playback_note", "") or "").strip()
    if playback_note:
        lines.extend(["", playback_note])
    if int(playback.get("samples", 0) or 0) < 30:
        low_sample = str(labels.get("search_telemetry_panel_low_sample_note", "") or "").strip()
        if low_sample:
            lines.extend(["", low_sample])
    if int(playback.get("samples", 0) or 0) >= 5:
        lines.extend(
            [
                "",
                str(labels.get("search_telemetry_panel_playback_percentiles", "播放绝对偏差分位")),
                f"p50 = {sec_value(playback.get('p50_abs_delta_sec'))}",
                f"p90 = {sec_value(playback.get('p90_abs_delta_sec'))}",
                f"p95 = {sec_value(playback.get('p95_abs_delta_sec'))}",
            ]
        )
    lines.extend(["", str(labels.get("search_telemetry_panel_confidence", "置信度分布"))])
    for tier_key in _TIER_ORDER:
        count = int(tiers.get(tier_key, 0) or 0)
        if total_tiers <= 0 and count <= 0:
            continue
        tier_label = str(labels.get(tier_key, tier_key))
        lines.append(f"{tier_label:<6} {pct_share(count)}")
    lines.extend(
        [
            "",
            str(
                labels.get(
                    "search_telemetry_panel_samples",
                    "样本：定位={locate} 播放={playback} 置信度={confidence}",
                ).format(
                    locate=int(crop.get("total", 0) or 0),
                    playback=int(playback.get("samples", 0) or 0),
                    confidence=total_tiers,
                )
            ),
        ]
    )
    return "\n".join(lines)


def format_telemetry_summary(*, language: str = "zh") -> str:
    summary = get_telemetry_summary()
    crop = summary.get("crop_locate") or {}
    playback = summary.get("playback_bias") or {}
    tiers = summary.get("confidence_tiers") or {}
    total_tiers = max(1, sum(int(v or 0) for v in tiers.values()))

    if language == "en":
        lines = [
            f"Search telemetry ({summary.get('updated_at') or '-'})",
            (
                "Crop locate anchor retention: "
                f"{crop.get('anchor_kept', 0)}/{crop.get('total', 0)} "
                f"({int(round(float(crop.get('retention_rate', 0.0)) * 100))}%)"
            ),
            "Confidence tiers:",
        ]
        for tier_key, count in sorted(tiers.items(), key=lambda item: (-int(item[1] or 0), item[0])):
            pct = int(round(int(count or 0) * 100 / total_tiers))
            lines.append(f"  {tier_key}: {count} ({pct}%)")
        lines.extend(
            [
                (
                    "Playback bias: "
                    f"samples={playback.get('samples', 0)} "
                    f"mean_abs_delta={float(playback.get('mean_abs_delta_sec', 0.0)):.2f}s "
                    f"within_1s={int(round(float(playback.get('within_1s_rate', 0.0)) * 100))}%"
                ),
            ]
        )
        return "\n".join(lines)

    lines = [
        f"搜索遥测 ({summary.get('updated_at') or '-'})",
        (
            "截图定位 anchor 保留: "
            f"{crop.get('anchor_kept', 0)}/{crop.get('total', 0)} "
            f"({int(round(float(crop.get('retention_rate', 0.0)) * 100))}%)"
        ),
        "置信度分布:",
    ]
    for tier_key, count in sorted(tiers.items(), key=lambda item: (-int(item[1] or 0), item[0])):
        pct = int(round(int(count or 0) * 100 / total_tiers))
        lines.append(f"  {tier_key}: {count} ({pct}%)")
    lines.append(
        (
            "播放偏差: "
            f"样本={playback.get('samples', 0)} "
            f"平均绝对偏差={float(playback.get('mean_abs_delta_sec', 0.0)):.2f}s "
            f"±1s内={int(round(float(playback.get('within_1s_rate', 0.0)) * 100))}%"
        )
    )
    return "\n".join(lines)


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
    if total % _SUMMARY_LOG_INTERVAL == 0:
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
    if p90 > _LOCATE_CLIP_P90_HIGH_SEC and (p90 - global_p90) >= P90_EFFECT_SIZE_MIN_SEC:
        current = min(_LOCATE_CLIP_BIAS_MAX_SEC, current + _LOCATE_CLIP_BIAS_STEP_SEC)
    elif p90 < _LOCATE_CLIP_P90_LOW_SEC and (global_p90 - p90) >= P90_EFFECT_SIZE_MIN_SEC:
        current = max(0.0, current - _LOCATE_CLIP_BIAS_STEP_SEC)
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
        if len(state.locate_clip_error_samples) > _LOCATE_CLIP_ERROR_SAMPLE_CAP:
            state.locate_clip_error_samples = state.locate_clip_error_samples[-_LOCATE_CLIP_ERROR_SAMPLE_CAP:]
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
        if len(state.locate_clip_signal_samples) > _LOCATE_CLIP_SIGNAL_SAMPLE_CAP:
            state.locate_clip_signal_samples = state.locate_clip_signal_samples[-_LOCATE_CLIP_SIGNAL_SAMPLE_CAP:]
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
            and bucket_samples % _LOCATE_CLIP_BIAS_SEGMENT_INTERVAL == 0
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


def record_crop_confidence(
    *,
    score: float,
    tier_key: str,
    source: str = "crop_search",
) -> None:
    if not is_telemetry_enabled():
        return

    tier = str(tier_key or "clip_confidence_low")
    src = str(source or "crop_search")
    with _lock:
        state = _ensure_state_locked()
        state.confidence_tiers[tier] = int(state.confidence_tiers.get(tier, 0)) + 1
        by_source = state.confidence_by_source.setdefault(src, {})
        by_source[tier] = int(by_source.get(tier, 0)) + 1
        state.updated_at = _now()
        _persist_locked(state)

    logger.info(
        "crop_confidence source=%s tier=%s score=%.4f",
        src,
        tier,
        float(score),
    )
    _maybe_add_profile_counter(f"telemetry_confidence_{tier}")
    _maybe_add_profile_counter(f"telemetry_confidence_{src}_{tier}")


def begin_playback_session(
    *,
    video_path: str,
    suggested_sec: float,
    playback_start_sec: float | None = None,
) -> None:
    if not is_telemetry_enabled():
        return
    global _pending_playback
    with _lock:
        _pending_playback = {
            "video_path": str(video_path or ""),
            "suggested_sec": float(suggested_sec),
            "playback_start_sec": float(playback_start_sec if playback_start_sec is not None else suggested_sec),
            "user_adjusted": False,
        }


def mark_playback_user_adjusted() -> None:
    if not is_telemetry_enabled():
        return
    global _pending_playback
    with _lock:
        if _pending_playback is not None:
            _pending_playback["user_adjusted"] = True


def cancel_playback_session() -> None:
    global _pending_playback
    with _lock:
        _pending_playback = None


def finish_playback_session(*, actual_sec: float | None, source: str = "inline") -> None:
    if not is_telemetry_enabled():
        return
    global _pending_playback
    with _lock:
        pending = dict(_pending_playback) if _pending_playback else None
        _pending_playback = None
    if not pending or actual_sec is None:
        return

    suggested = float(pending.get("suggested_sec", 0.0))
    actual = max(0.0, float(actual_sec))
    delta = actual - suggested
    abs_delta = abs(delta)
    user_adjusted = bool(pending.get("user_adjusted"))

    if not user_adjusted:
        with _lock:
            state = _ensure_state_locked()
            state.playback_passive_skipped += 1
            state.updated_at = _now()
            _persist_locked(state)
        logger.info(
            "playback_bias_skipped passive=1 source=%s suggested=%.3f actual=%.3f delta=%.3f start=%.3f video=%s",
            str(source or "inline"),
            suggested,
            actual,
            delta,
            float(pending.get("playback_start_sec", suggested)),
            os.path.basename(str(pending.get("video_path") or "")) or "-",
        )
        return

    with _lock:
        state = _ensure_state_locked()
        state.playback_samples += 1
        state.playback_abs_delta_sum_sec += abs_delta
        state.playback_abs_delta_samples.append(abs_delta)
        if len(state.playback_abs_delta_samples) > _PLAYBACK_DELTA_SAMPLE_CAP:
            state.playback_abs_delta_samples = state.playback_abs_delta_samples[-_PLAYBACK_DELTA_SAMPLE_CAP:]
        if abs_delta <= 1.0:
            state.playback_within_1s += 1
        if abs_delta <= 5.0:
            state.playback_within_5s += 1
        state.updated_at = _now()
        _persist_locked(state)

    logger.info(
        "playback_bias source=%s adjusted=1 suggested=%.3f actual=%.3f delta=%.3f video=%s",
        str(source or "inline"),
        suggested,
        actual,
        delta,
        os.path.basename(str(pending.get("video_path") or "")) or "-",
    )
    _maybe_add_profile_counter("telemetry_playback_samples")
    if abs_delta <= 1.0:
        _maybe_add_profile_counter("telemetry_playback_within_1s")
    if abs_delta <= 5.0:
        _maybe_add_profile_counter("telemetry_playback_within_5s")


def log_telemetry_summary() -> None:
    if not is_telemetry_enabled():
        return
    with _lock:
        _log_summary_locked()


def _ensure_state_locked() -> SearchTelemetryState:
    global _state
    if _state is None:
        _state = _load_state()
    return _state


def _load_state() -> SearchTelemetryState:
    path = get_telemetry_file_path()
    if not os.path.isfile(path):
        return SearchTelemetryState(updated_at=_now())
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return SearchTelemetryState.from_dict(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Failed to load search telemetry file: %s", path)
    return SearchTelemetryState(updated_at=_now())


def _persist_locked(state: SearchTelemetryState) -> None:
    path = get_telemetry_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    payload = state.to_dict()
    playback = dict(payload.get("playback_bias") or {})
    playback["abs_delta_samples"] = list(state.playback_abs_delta_samples)
    payload["playback_bias"] = playback
    locate_clip = dict(payload.get("locate_clip_window") or {})
    locate_clip["error_samples"] = list(state.locate_clip_error_samples)
    locate_clip["signal_samples"] = list(state.locate_clip_signal_samples)
    payload["locate_clip_window"] = locate_clip
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _log_summary_locked() -> None:
    state = _ensure_state_locked()
    summary = state.to_dict()
    crop = summary["crop_locate"]
    playback = summary["playback_bias"]
    logger.info(
        "telemetry_summary locate_total=%s anchor_retention=%.1f%% playback_samples=%s mean_abs_delta=%.2fs within_1s=%.1f%%",
        crop["total"],
        float(crop.get("retention_rate", 0.0)) * 100.0,
        playback["samples"],
        float(playback.get("mean_abs_delta_sec", 0.0)),
        float(playback.get("within_1s_rate", 0.0)) * 100.0,
    )


def _maybe_add_profile_counter(name: str, delta: int = 1) -> None:
    try:
        from src.services.search_profiling import add_profile_counter, profiling_active

        if profiling_active():
            add_profile_counter(name, delta)
    except Exception:
        pass


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _mean(total: float, count: int) -> float:
    if count <= 0:
        return 0.0
    return float(total) / float(count)


def _normalize_signal_samples(raw_samples) -> list[dict[str, float | str]]:
    if not isinstance(raw_samples, list):
        return []
    samples: list[dict[str, float | str]] = []
    for item in raw_samples:
        if not isinstance(item, dict):
            continue
        try:
            samples.append(
                {
                    "score": float(item.get("score", -1.0)),
                    "margin": float(item.get("margin", -1.0)),
                    "confidence": float(item.get("confidence", -1.0)),
                    "error_sec": max(0.0, float(item.get("error_sec", 0.0))),
                    "window_sec": float(item.get("window_sec", 0.0)),
                    "score_bucket": str(item.get("score_bucket") or "unknown"),
                    "pace": str(item.get("pace") or "unknown"),
                }
            )
        except (TypeError, ValueError):
            continue
    if len(samples) > _LOCATE_CLIP_SIGNAL_SAMPLE_CAP:
        samples = samples[-_LOCATE_CLIP_SIGNAL_SAMPLE_CAP:]
    return samples


def _normalize_delta_samples(raw_samples) -> list[float]:
    if not isinstance(raw_samples, list):
        return []
    samples: list[float] = []
    for item in raw_samples:
        try:
            value = max(0.0, float(item))
        except (TypeError, ValueError):
            continue
        samples.append(value)
    if len(samples) > _PLAYBACK_DELTA_SAMPLE_CAP:
        samples = samples[-_PLAYBACK_DELTA_SAMPLE_CAP:]
    return samples


def _percentile(samples: list[float], percentile: int) -> float | None:
    if not samples:
        return None
    ordered = sorted(float(value) for value in samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (float(percentile) / 100.0) * float(len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - float(lower)
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
