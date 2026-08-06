"""Localhost Agent API (v1): health, search, library discovery, clip export."""

from __future__ import annotations

import importlib
import os

importlib.import_module("src.services.library_service")

from src.app.config import load_config

from .constants import (
    API_VERSION,
    DEFAULT_FRAME_PAD_AFTER_SEC,
    DEFAULT_FRAME_PAD_BEFORE_SEC,
    DEFAULT_HOST,
    DEFAULT_PORT,
    MAX_BATCH_QUERIES,
    MAX_CONCURRENT_SEARCHES,
    SearchEngineBusyError,
    acquire_search_slot,
    configure_search_concurrency,
    get_max_concurrent_searches,
    get_search_queue_wait_sec,
)
from .errors import IndexNotReadyError, api_error_payload, raise_api_error
from .export_ops import (
    build_batch_export_items_from_search_results,
    dedupe_manifest_items,
    execute_export_manifest,
)
from .health import (
    _agent_timeout_settings,
    _build_ffmpeg_info,
    _index_snapshot,
    _normalize_mode,
    build_health_payload,
    build_health_ping_payload,
)
from .schemas import (
    AgentBatchExportClipItem,
    AgentBatchExportClipsRequest,
    AgentBatchSearchExportOptions,
    AgentBatchSearchRequest,
    AgentExportClipRequest,
    AgentManifestItem,
    AgentManifestRequest,
    AgentSearchRequest,
    AgentSearchScope,
)
from .search import (
    _batch_requests_precise_mode,
    _clamp_top_k,
    _enrich_hit_payload,
    _expand_clip_window,
    _expand_image_folder,
    _filter_hits,
    _hits_to_payload,
    _per_library_indexes_ready,
    _resolve_agent_search_inputs,
    _resolve_batch_timeout_sec,
    _resolve_search_timeout_sec,
    _search_index_ready_for_request,
    execute_agent_batch_search,
    execute_agent_search,
    get_agent_search_preset,
    get_agent_search_telemetry,
    list_agent_search_presets,
)
from .export_ops import _format_timecode
from .service import AgentApiService

__all__ = [
    "API_VERSION",
    "AgentApiService",
    "AgentBatchExportClipItem",
    "AgentBatchExportClipsRequest",
    "AgentBatchSearchExportOptions",
    "AgentBatchSearchRequest",
    "AgentExportClipRequest",
    "AgentManifestItem",
    "AgentManifestRequest",
    "AgentSearchRequest",
    "AgentSearchScope",
    "DEFAULT_FRAME_PAD_AFTER_SEC",
    "DEFAULT_FRAME_PAD_BEFORE_SEC",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "IndexNotReadyError",
    "MAX_BATCH_QUERIES",
    "MAX_CONCURRENT_SEARCHES",
    "SearchEngineBusyError",
    "acquire_search_slot",
    "configure_search_concurrency",
    "get_max_concurrent_searches",
    "get_search_queue_wait_sec",
    "_agent_timeout_settings",
    "_batch_requests_precise_mode",
    "_build_ffmpeg_info",
    "_clamp_top_k",
    "_enrich_hit_payload",
    "_expand_clip_window",
    "_expand_image_folder",
    "_filter_hits",
    "_format_timecode",
    "_hits_to_payload",
    "_index_snapshot",
    "_per_library_indexes_ready",
    "_resolve_agent_search_inputs",
    "_resolve_batch_timeout_sec",
    "_resolve_search_timeout_sec",
    "_search_index_ready_for_request",
    "agent_api_enabled",
    "api_error_payload",
    "build_batch_export_items_from_search_results",
    "build_health_payload",
    "build_health_ping_payload",
    "dedupe_manifest_items",
    "execute_agent_batch_search",
    "execute_agent_search",
    "execute_export_manifest",
    "get_agent_search_preset",
    "get_agent_search_telemetry",
    "is_agent_api_enabled",
    "list_agent_search_presets",
    "raise_api_error",
]


def is_agent_api_enabled(config=None) -> bool:
    """Whether the Agent API should run (config + env override + team server mode)."""
    forced = str(os.environ.get("VIDEOSEEK_AGENT_API", "")).strip().lower()
    if forced in {"0", "false", "no", "off"}:
        return False
    if forced in {"1", "true", "yes", "on"}:
        return True
    if config is None:
        config = load_config()
    from src.services.team_mode_service import is_team_server_mode

    if is_team_server_mode(config):
        return True
    return bool(config.get("agent_api_enabled", False))


def agent_api_enabled() -> bool:
    return is_agent_api_enabled()
