"""Pydantic request/response schemas for the Agent API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._fastapi import BaseModel, Field
from .constants import DEFAULT_FRAME_PAD_AFTER_SEC, DEFAULT_FRAME_PAD_BEFORE_SEC


class AgentSearchScope(BaseModel):
    video_paths: Optional[List[str]] = None
    library_paths: Optional[List[str]] = None
    use_saved_scope: bool = False


class AgentSearchRequest(BaseModel):
    query: Optional[str] = None
    preset_id: Optional[str] = None
    query_type: str = "text"
    # Alias for image search: same as query + query_type=image_path
    image_path: Optional[str] = None
    # Team client upload: decode to a temp file on the server
    image_base64: Optional[str] = None
    image_mime: Optional[str] = None
    # visual (default) | dialogue | tags — orthogonal to mode frame/chunk
    search_kind: Optional[str] = None
    top_k: Optional[int] = None
    mode: Optional[str] = None
    search_mode: Optional[str] = None  # alias of mode for team clients
    min_score: Optional[float] = None
    search_precision_mode: Optional[str] = None
    # Image search: keep best hit per video (desktop 「视频择优」).
    video_discovery_enabled: Optional[bool] = None
    # Precomputed CLIP vector (compose / presets). When set, server skips re-encoding.
    query_vector: Optional[List[float]] = None
    # Dialogue/tags: exact | fuzzy | auto (team clients may also send via search_mode).
    match_mode: Optional[str] = None
    # Visual text search: multi-route CLIP + RRF. null = use server text_search_enhance_enabled.
    text_enhance: Optional[bool] = None
    client_request_id: Optional[str] = None
    scope: Optional[AgentSearchScope] = None
    expand_frame_hits: bool = True
    pad_before_sec: float = DEFAULT_FRAME_PAD_BEFORE_SEC
    pad_after_sec: float = DEFAULT_FRAME_PAD_AFTER_SEC
    preview_anchor_sec: Optional[float] = None
    team_play_urls: bool = False


class AgentBatchSearchExportOptions(BaseModel):
    """Optional: export top hits after batch search (no separate items[] glue)."""

    output_dir: str
    encode_mode: Optional[str] = "copy"
    silent: Optional[bool] = None
    keep_per_source: int = Field(default=1, ge=1, le=50)
    dedupe: bool = True
    continue_on_error: bool = True


class AgentBatchSearchRequest(BaseModel):
    """Batch search: explicit queries and/or all images under image_folder."""

    queries: List[AgentSearchRequest] = Field(default_factory=list)
    image_folder: Optional[str] = None
    search_kind: Optional[str] = None
    top_k: Optional[int] = None
    mode: Optional[str] = None
    min_score: Optional[float] = None
    search_precision_mode: Optional[str] = None
    video_discovery_enabled: Optional[bool] = None
    text_enhance: Optional[bool] = None
    continue_on_error: bool = True
    scope: Optional[AgentSearchScope] = None
    expand_frame_hits: bool = True
    pad_before_sec: float = DEFAULT_FRAME_PAD_BEFORE_SEC
    pad_after_sec: float = DEFAULT_FRAME_PAD_AFTER_SEC
    export: Optional[AgentBatchSearchExportOptions] = None


class AgentManifestItem(BaseModel):
    id: Optional[str] = None
    query: Optional[str] = None
    client_request_id: Optional[str] = None
    video_path: str
    start_sec: float
    end_sec: float
    score: Optional[float] = None
    rank: Optional[int] = None
    notes: Optional[str] = None


class AgentManifestRequest(BaseModel):
    project: str = "rough-cut"
    items: Optional[List[AgentManifestItem]] = None
    sources: Optional[List[Dict[str, Any]]] = None
    keep_per_source: int = Field(default=2, ge=1, le=50)
    dedupe: bool = True
    write_path: Optional[str] = None
    expand_frame_hits: bool = True
    pad_before_sec: float = DEFAULT_FRAME_PAD_BEFORE_SEC
    pad_after_sec: float = DEFAULT_FRAME_PAD_AFTER_SEC
    mode: Optional[str] = None


class AgentFrameExtractRequest(BaseModel):
    """Single-frame JPEG extract at time_sec (local video_path on the API host)."""

    video_path: str
    time_sec: float
    # Longest edge after optional downscale (64–1920); default applied in execute.
    max_edge: Optional[int] = None
    client_request_id: Optional[str] = None


class AgentBatchFrameExtractRequest(BaseModel):
    """Batch single-frame extracts (JPEG base64). Default max_edge applies to items that omit it."""

    items: List[AgentFrameExtractRequest] = Field(default_factory=list)
    max_edge: Optional[int] = None
    continue_on_error: bool = True


class AgentTimelineClipItem(BaseModel):
    """One clip for timeline export: point (time_sec) or range (start_sec/end_sec)."""

    video_path: str
    time_sec: Optional[float] = None
    start_sec: Optional[float] = None
    end_sec: Optional[float] = None
    client_request_id: Optional[str] = None


class AgentTimelineExportRequest(BaseModel):
    """Multi-clip NLE/Jianying timeline: jianying | fcpxml | fcp7_xml."""

    format: str
    items: List[AgentTimelineClipItem] = Field(default_factory=list)
    project: Optional[str] = None
    # XML: full file path, or output_dir (+ auto filename). Jianying ignores these.
    write_path: Optional[str] = None
    output_dir: Optional[str] = None
    drafts_dir: Optional[str] = None
    draft_name: Optional[str] = None
    client_request_id: Optional[str] = None


class AgentExportClipRequest(BaseModel):
    video_path: str
    start_sec: float
    end_sec: float
    # Provide output_path (full file) or output_dir (auto filename), not both.
    output_path: Optional[str] = None
    output_dir: Optional[str] = None
    client_request_id: Optional[str] = None
    silent: Optional[bool] = None
    encode_mode: Optional[str] = "copy"


class AgentBatchExportClipItem(BaseModel):
    video_path: str
    start_sec: float
    end_sec: float
    output_path: str
    client_request_id: Optional[str] = None
    silent: Optional[bool] = None
    encode_mode: Optional[str] = None


class AgentBatchExportClipsRequest(BaseModel):
    items: List[AgentBatchExportClipItem] = Field(default_factory=list)
    silent: Optional[bool] = None
    encode_mode: Optional[str] = "copy"
    continue_on_error: bool = True
