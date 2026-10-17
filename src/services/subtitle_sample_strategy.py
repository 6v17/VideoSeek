"""Lightweight subtitle sample-strategy constants (no OCR/VAD imports)."""

from __future__ import annotations

from typing import Literal

SubtitleSampleStrategy = Literal["timeline", "vad"]

SUBTITLE_SAMPLE_STRATEGY_TIMELINE = "timeline"
SUBTITLE_SAMPLE_STRATEGY_VAD = "vad"
DEFAULT_SUBTITLE_SAMPLE_STRATEGY = SUBTITLE_SAMPLE_STRATEGY_TIMELINE


def normalize_subtitle_sample_strategy(value: str | None) -> SubtitleSampleStrategy:
    text = str(value or "").strip().lower()
    if text in {"vad", "speech", "fast"}:
        return SUBTITLE_SAMPLE_STRATEGY_VAD
    if text in {"timeline", "full", "probe", "pv"}:
        return SUBTITLE_SAMPLE_STRATEGY_TIMELINE
    return DEFAULT_SUBTITLE_SAMPLE_STRATEGY


def resolve_subtitle_sample_strategy(*, config=None, explicit: str | None = None) -> SubtitleSampleStrategy:
    if explicit is not None and str(explicit).strip():
        return normalize_subtitle_sample_strategy(explicit)
    try:
        from src.app.config import DEFAULT_CONFIG, load_config

        cfg = dict(config or load_config())
        return normalize_subtitle_sample_strategy(
            cfg.get(
                "subtitle_sample_strategy",
                DEFAULT_CONFIG.get("subtitle_sample_strategy", DEFAULT_SUBTITLE_SAMPLE_STRATEGY),
            )
        )
    except Exception:
        return DEFAULT_SUBTITLE_SAMPLE_STRATEGY
