"""Crop confidence tier telemetry."""

from __future__ import annotations

from src.services.search_telemetry_store import (
    _ensure_state_locked,
    _lock,
    _maybe_add_profile_counter,
    _now,
    _persist_locked,
    is_telemetry_enabled,
    logger,
)

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
