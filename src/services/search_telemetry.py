"""Search telemetry facade: crop locate, playback bias, confidence tiers."""

from __future__ import annotations

from src.services.search_telemetry_format import format_telemetry_panel, format_telemetry_summary
from src.services.search_telemetry_locate import (
    get_locate_clip_window_bias_sec,
    record_crop_locate_anchor,
    record_locate_clip_window,
)
from src.services.search_telemetry_playback import (
    begin_playback_session,
    cancel_playback_session,
    finish_playback_session,
    mark_playback_user_adjusted,
)
from src.services.search_telemetry_store import (
    SearchTelemetryState,
    _lock,
    _pending_playback,
    _state,
    get_locate_signal_samples,
    get_telemetry_file_path,
    get_telemetry_summary,
    is_locate_bias_auto_tune_enabled,
    is_telemetry_enabled,
    log_telemetry_summary,
    reload_telemetry_state,
)
from src.services.search_telemetry_confidence import record_crop_confidence

__all__ = [
    "SearchTelemetryState",
    "begin_playback_session",
    "cancel_playback_session",
    "finish_playback_session",
    "format_telemetry_panel",
    "format_telemetry_summary",
    "get_locate_clip_window_bias_sec",
    "get_locate_signal_samples",
    "get_telemetry_file_path",
    "get_telemetry_summary",
    "is_locate_bias_auto_tune_enabled",
    "is_telemetry_enabled",
    "log_telemetry_summary",
    "mark_playback_user_adjusted",
    "record_crop_confidence",
    "record_crop_locate_anchor",
    "record_locate_clip_window",
    "reload_telemetry_state",
]
