"""Persistent search telemetry state and JSON storage."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.app.config import DEFAULT_CONFIG
from src.app.logging_utils import get_app_data_dir, get_logger

logger = get_logger("search_telemetry_store")

_TELEMETRY_VERSION = 5
SUMMARY_LOG_INTERVAL = 10
PLAYBACK_DELTA_SAMPLE_CAP = 5000
LOCATE_CLIP_ERROR_SAMPLE_CAP = 5000
LOCATE_CLIP_SIGNAL_SAMPLE_CAP = 5000
LOCATE_CLIP_BIAS_SEGMENT_INTERVAL = 50
LOCATE_CLIP_P90_HIGH_SEC = 3.0
LOCATE_CLIP_P90_LOW_SEC = 1.0
LOCATE_CLIP_BIAS_STEP_SEC = 5.0
LOCATE_CLIP_BIAS_MAX_SEC = 15.0

TIER_ORDER = (
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
    if len(samples) > LOCATE_CLIP_SIGNAL_SAMPLE_CAP:
        samples = samples[-LOCATE_CLIP_SIGNAL_SAMPLE_CAP:]
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
    if len(samples) > PLAYBACK_DELTA_SAMPLE_CAP:
        samples = samples[-PLAYBACK_DELTA_SAMPLE_CAP:]
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
