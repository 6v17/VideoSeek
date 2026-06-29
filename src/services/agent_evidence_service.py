"""Agent API helpers for optional understanding evidence bundles."""

from __future__ import annotations

import os
from typing import Any

from src.app.config import load_config
from src.services.search_chunk_pipeline import _resolve_video_id_for_path
from src.services.search_scope import normalize_scope_path
from src.services.understanding_resource_service import get_understanding_resource_status
from src.services.understanding_service import (
    UnderstandingGenerationError,
    generate_evidence_for_video,
    load_evidence_bundle,
    resolve_video_context,
)

API_VERSION = "1"
_UNDERSTANDING_TIMEOUT_FALLBACK_SEC = 600.0
_UNDERSTANDING_TIMEOUT_PER_CHUNK_SEC = 30.0
_UNDERSTANDING_TIMEOUT_MAX_SEC = 3600.0
_UNDERSTANDING_TIMEOUT_MIN_SEC = 120.0


class AgentEvidenceError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def resolve_agent_video_id(
    *,
    video_id: str | None = None,
    video_path: str | None = None,
    config=None,
) -> str:
    cfg = config or load_config()
    video_id_text = str(video_id or "").strip()
    video_path_text = str(video_path or "").strip()
    if video_id_text and video_path_text:
        resolved = _resolve_video_id_for_path(video_path_text, cfg)
        if resolved and resolved != video_id_text:
            raise AgentEvidenceError(
                "invalid_request",
                "video_id does not match video_path",
                status_code=400,
            )
        return video_id_text
    if video_id_text:
        return video_id_text
    if not video_path_text:
        raise AgentEvidenceError(
            "invalid_request",
            "video_id or video_path is required",
            status_code=400,
        )
    resolved = _resolve_video_id_for_path(video_path_text, cfg)
    if not resolved:
        raise AgentEvidenceError(
            "video_not_found",
            f"Video path is not indexed: {normalize_scope_path(video_path_text)}",
            status_code=422,
        )
    return resolved


def resolve_understanding_timeout_sec(*, chunk_count: int, config=None) -> float:
    cfg = config or load_config()
    try:
        base = float(cfg.get("agent_api_understanding_timeout_sec", _UNDERSTANDING_TIMEOUT_FALLBACK_SEC))
    except (TypeError, ValueError):
        base = _UNDERSTANDING_TIMEOUT_FALLBACK_SEC
    try:
        per_chunk = float(
            cfg.get("agent_api_understanding_timeout_per_chunk_sec", _UNDERSTANDING_TIMEOUT_PER_CHUNK_SEC)
        )
    except (TypeError, ValueError):
        per_chunk = _UNDERSTANDING_TIMEOUT_PER_CHUNK_SEC
    estimated = base + per_chunk * max(0, int(chunk_count) - 1)
    return min(_UNDERSTANDING_TIMEOUT_MAX_SEC, max(_UNDERSTANDING_TIMEOUT_MIN_SEC, estimated))


def filter_evidence_bundle_by_time_window(
    bundle: dict[str, Any],
    *,
    start_sec: float | None = None,
    end_sec: float | None = None,
) -> dict[str, Any]:
    if start_sec is None and end_sec is None:
        return dict(bundle)
    window_start = float("-inf") if start_sec is None else float(start_sec)
    window_end = float("inf") if end_sec is None else float(end_sec)
    if window_start > window_end:
        raise AgentEvidenceError(
            "invalid_request",
            "start_sec must be <= end_sec",
            status_code=400,
        )
    payload = dict(bundle)
    chunks = list(payload.get("chunks") or [])
    payload["chunks"] = [
        chunk
        for chunk in chunks
        if isinstance(chunk, dict)
        and float(chunk.get("end_sec", 0.0)) >= window_start
        and float(chunk.get("start_sec", 0.0)) <= window_end
    ]
    return payload


def _empty_evidence_payload(
    *,
    video_id: str,
    video_context: dict[str, Any] | None,
    start_sec: float | None,
    end_sec: float | None,
    ensure: bool,
) -> dict[str, Any]:
    video = dict((video_context or {}).get("video") or {})
    if not video:
        video = {
            "video_id": video_id,
            "video_path": str((video_context or {}).get("video_path") or ""),
        }
    return {
        "api_version": API_VERSION,
        "ok": True,
        "evidence_available": False,
        "video_id": video_id,
        "video": video,
        "provenance": None,
        "summary": None,
        "chunks": [],
        "meta": {
            "ensure": bool(ensure),
            "filtered_start_sec": start_sec,
            "filtered_end_sec": end_sec,
            "generated_by": None,
        },
    }


def _bundle_response_payload(
    bundle: dict[str, Any],
    *,
    video_id: str,
    start_sec: float | None,
    end_sec: float | None,
    generated_by: str | None = None,
) -> dict[str, Any]:
    filtered = filter_evidence_bundle_by_time_window(bundle, start_sec=start_sec, end_sec=end_sec)
    video = dict(filtered.get("video") or {})
    if not video.get("video_id"):
        video["video_id"] = video_id
    summary = filtered.get("summary")
    provenance = filtered.get("provenance")
    return {
        "api_version": API_VERSION,
        "ok": True,
        "evidence_available": True,
        "video_id": str(video.get("video_id") or video_id),
        "video": video,
        "provenance": provenance if isinstance(provenance, dict) else None,
        "summary": summary if isinstance(summary, dict) else None,
        "chunks": list(filtered.get("chunks") or []),
        "meta": {
            "filtered_start_sec": start_sec,
            "filtered_end_sec": end_sec,
            "generated_by": generated_by,
            "chunk_count": len(filtered.get("chunks") or []),
        },
    }


def _map_generation_error(exc: UnderstandingGenerationError) -> AgentEvidenceError:
    message = str(exc)
    lowered = message.lower()
    if "not ready" in lowered or "missing:" in lowered:
        return AgentEvidenceError("understanding_not_ready", message, status_code=409)
    if "no semantic chunks" in lowered:
        return AgentEvidenceError("no_chunks", message, status_code=422)
    if "source file is missing" in lowered or "not found in library metadata" in lowered:
        return AgentEvidenceError("video_not_found", message, status_code=422)
    return AgentEvidenceError("query_failed", message, status_code=422)


def get_agent_video_evidence(
    *,
    video_id: str | None = None,
    video_path: str | None = None,
    start_sec: float | None = None,
    end_sec: float | None = None,
    ensure: bool = False,
    config=None,
) -> dict[str, Any]:
    cfg = config or load_config()
    if start_sec is not None and end_sec is not None and float(start_sec) > float(end_sec):
        raise AgentEvidenceError(
            "invalid_request",
            "start_sec must be <= end_sec",
            status_code=400,
        )

    resolved_video_id = resolve_agent_video_id(video_id=video_id, video_path=video_path, config=cfg)
    try:
        video_context = resolve_video_context(resolved_video_id, config=cfg)
    except UnderstandingGenerationError as exc:
        raise _map_generation_error(exc) from exc

    existing = load_evidence_bundle(resolved_video_id, config=cfg)
    if existing:
        return _bundle_response_payload(
            existing,
            video_id=resolved_video_id,
            start_sec=start_sec,
            end_sec=end_sec,
        )

    if not ensure:
        return _empty_evidence_payload(
            video_id=resolved_video_id,
            video_context={"video_path": video_context.get("video_path"), "video": {"video_id": resolved_video_id, "video_path": video_context.get("video_path")}},
            start_sec=start_sec,
            end_sec=end_sec,
            ensure=False,
        )

    status = get_understanding_resource_status(config=cfg, probe_remote=True)
    if not status.get("understanding_ready"):
        missing = ", ".join(status.get("missing_components") or []) or "unknown"
        raise AgentEvidenceError(
            "understanding_not_ready",
            f"Understanding resources are not ready (missing: {missing})",
            status_code=409,
        )

    try:
        generate_evidence_for_video(resolved_video_id, config=cfg)
    except UnderstandingGenerationError as exc:
        raise _map_generation_error(exc) from exc

    bundle = load_evidence_bundle(resolved_video_id, config=cfg)
    if not bundle:
        raise AgentEvidenceError(
            "query_failed",
            f"Evidence bundle was not written for video: {resolved_video_id}",
            status_code=422,
        )
    return _bundle_response_payload(
        bundle,
        video_id=resolved_video_id,
        start_sec=start_sec,
        end_sec=end_sec,
        generated_by="agent_api",
    )


def build_agent_understanding_health_fields(*, config=None, probe_remote: bool = False) -> dict[str, Any]:
    cfg = config or load_config()
    status = get_understanding_resource_status(config=cfg, probe_remote=probe_remote)
    return {
        "understanding_ready": bool(status.get("understanding_ready")),
        "active_understanding_profile": str(status.get("active_understanding_profile") or ""),
        "understanding_missing_components": list(status.get("missing_components") or []),
        "understanding_optional_missing_components": list(status.get("optional_missing_components") or []),
    }
