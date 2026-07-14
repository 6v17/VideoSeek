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
    top_k: Optional[int] = None
    mode: Optional[str] = None
    min_score: Optional[float] = None
    search_precision_mode: Optional[str] = None
    client_request_id: Optional[str] = None
    scope: Optional[AgentSearchScope] = None
    expand_frame_hits: bool = True
    pad_before_sec: float = DEFAULT_FRAME_PAD_BEFORE_SEC
    pad_after_sec: float = DEFAULT_FRAME_PAD_AFTER_SEC
    preview_anchor_sec: Optional[float] = None


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
    top_k: Optional[int] = None
    mode: Optional[str] = None
    min_score: Optional[float] = None
    search_precision_mode: Optional[str] = None
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


class AgentExportClipRequest(BaseModel):
    video_path: str
    start_sec: float
    end_sec: float
    output_path: str
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
