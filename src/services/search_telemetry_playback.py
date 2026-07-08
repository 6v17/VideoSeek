"""Playback bias telemetry (user seek vs suggested timestamp)."""

from __future__ import annotations

import os

import src.services.search_telemetry_store as store
from src.services.search_telemetry_store import (
    PLAYBACK_DELTA_SAMPLE_CAP,
    is_telemetry_enabled,
    logger,
)


def begin_playback_session(
    *,
    video_path: str,
    suggested_sec: float,
    playback_start_sec: float | None = None,
) -> None:
    if not is_telemetry_enabled():
        return
    with store._lock:
        store._pending_playback = {
            "video_path": str(video_path or ""),
            "suggested_sec": float(suggested_sec),
            "playback_start_sec": float(playback_start_sec if playback_start_sec is not None else suggested_sec),
            "user_adjusted": False,
        }


def mark_playback_user_adjusted() -> None:
    if not is_telemetry_enabled():
        return
    with store._lock:
        if store._pending_playback is not None:
            store._pending_playback["user_adjusted"] = True


def cancel_playback_session() -> None:
    with store._lock:
        store._pending_playback = None


def finish_playback_session(*, actual_sec: float | None, source: str = "inline") -> None:
    if not is_telemetry_enabled():
        return
    with store._lock:
        pending = dict(store._pending_playback) if store._pending_playback else None
        store._pending_playback = None
    if not pending or actual_sec is None:
        return

    suggested = float(pending.get("suggested_sec", 0.0))
    actual = max(0.0, float(actual_sec))
    delta = actual - suggested
    abs_delta = abs(delta)
    user_adjusted = bool(pending.get("user_adjusted"))

    if not user_adjusted:
        with store._lock:
            state = store._ensure_state_locked()
            state.playback_passive_skipped += 1
            state.updated_at = store._now()
            store._persist_locked(state)
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

    with store._lock:
        state = store._ensure_state_locked()
        state.playback_samples += 1
        state.playback_abs_delta_sum_sec += abs_delta
        state.playback_abs_delta_samples.append(abs_delta)
        if len(state.playback_abs_delta_samples) > PLAYBACK_DELTA_SAMPLE_CAP:
            state.playback_abs_delta_samples = state.playback_abs_delta_samples[-PLAYBACK_DELTA_SAMPLE_CAP:]
        if abs_delta <= 1.0:
            state.playback_within_1s += 1
        if abs_delta <= 5.0:
            state.playback_within_5s += 1
        state.updated_at = store._now()
        store._persist_locked(state)

    logger.info(
        "playback_bias source=%s adjusted=1 suggested=%.3f actual=%.3f delta=%.3f video=%s",
        str(source or "inline"),
        suggested,
        actual,
        delta,
        os.path.basename(str(pending.get("video_path") or "")) or "-",
    )
    store._maybe_add_profile_counter("telemetry_playback_samples")
    if abs_delta <= 1.0:
        store._maybe_add_profile_counter("telemetry_playback_within_1s")
    if abs_delta <= 5.0:
        store._maybe_add_profile_counter("telemetry_playback_within_5s")
