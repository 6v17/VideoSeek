"""Short paste-ready onboarding text for external agents (Cursor, Claude, scripts)."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from src.utils import get_resource_path

# Relative to VideoSeek install / repo root (same layout for dev and Nuitka output).
AGENT_DOC_REL = "docs/for-agents.md"


def agent_doc_rel_path() -> str:
    return AGENT_DOC_REL


def resolve_full_agent_doc_path() -> Optional[str]:
    """Absolute path when the doc exists beside the app root (exe dir when frozen)."""
    candidate = os.path.normpath(get_resource_path(AGENT_DOC_REL))
    if os.path.isfile(candidate):
        return candidate
    return None


def _cap_lines(capabilities: Dict[str, Any]) -> str:
    if not capabilities:
        return "- (unknown)"
    enabled = [key for key, value in sorted(capabilities.items()) if value]
    disabled = [key for key, value in sorted(capabilities.items()) if not value]
    lines = [f"- enabled: {', '.join(enabled) or 'none'}"]
    if disabled:
        lines.append(f"- disabled: {', '.join(disabled)}")
    return "\n".join(lines)


def build_agent_starter_text(
    base_url: str,
    health: Dict[str, Any],
    *,
    locale: str = "zh",
) -> str:
    """Build ~80-line paste block: intro + live /health snapshot + minimal workflow."""
    lang = "en" if str(locale).lower().startswith("en") else "zh"
    base = str(base_url or "").rstrip("/")
    api_base = f"{base}/api/v1" if base else "http://127.0.0.1:8765/api/v1"
    doc_rel = agent_doc_rel_path()
    doc_on_disk = resolve_full_agent_doc_path() is not None

    caps = health.get("capabilities") or {}
    ffmpeg = health.get("ffmpeg") or {}
    index_ready = bool(health.get("index_ready"))

    if lang == "en":
        intro = (
            "You are a rough-cut assistant using VideoSeek on this PC.\n"
            "VideoSeek finds shots by VISUAL meaning (not dialogue). API is localhost-only.\n"
            "Do not rebuild indexes or change VideoSeek settings unless the user asks."
        )
        snapshot_title = "## This instance (from /health)"
        workflow_title = "## Minimal workflow"
        workflow = (
            "1. GET {api}/health — stop if index_ready is false.\n"
            "2. GET {api}/libraries — use library_path in scope.library_paths (do not guess folders).\n"
            "3. Rewrite script beats into short visual queries (concrete scene/action, not literal dialogue).\n"
            "4. POST {api}/search or {api}/search/batch — expand_frame_hits=true; image queries: search_precision_mode=precise.\n"
            "5. POST {api}/export/manifest — sources=<batch.results>, dedupe=true, keep_per_source=1-2.\n"
            "6. POST {api}/export/clip per kept hit (output_path must be outside indexed library roots).\n"
            "7. If export_clip is false, shell ffmpeg using ffmpeg_path below."
        ).format(api=api_base)
        doc_line = f"Full API contract: {doc_rel} (relative to VideoSeek install root)."
        if not doc_on_disk:
            doc_line += " File not found on disk — ask the user to ship docs/for-agents.md next to the app."
        not_ready = "Index not ready — ask the user to sync the library in VideoSeek before searching."
    else:
        intro = (
            "你是本机 VideoSeek 的粗剪编排助手。\n"
            "VideoSeek 按画面语义找镜头（不能按台词/剧情搜）。API 仅本机 localhost。\n"
            "除非用户明确要求，不要重建索引或修改 VideoSeek 设置。"
        )
        snapshot_title = "## 当前实例（/health 快照）"
        workflow_title = "## 最小流程"
        workflow = (
            "1. GET {api}/health — index_ready 为 false 则停止，让用户先在 VideoSeek 同步索引。\n"
            "2. GET {api}/libraries — scope.library_paths 用返回的 library_path，不要猜目录。\n"
            "3. 把脚本改写成短视觉 query（具体画面/动作，不要搜原文台词）。\n"
            "4. POST {api}/search 或 {api}/search/batch — expand_frame_hits=true；图搜加 search_precision_mode=precise。\n"
            "5. POST {api}/export/manifest — sources=<batch.results>, dedupe=true, keep_per_source=1-2。\n"
            "6. POST {api}/export/clip 逐条导出（output_path 不能在已索引库目录内）。\n"
            "7. 若 export_clip 为 false，用下方 ffmpeg_path 手动切条。"
        ).format(api=api_base)
        doc_line = f"完整 API 契约：{doc_rel}（相对 VideoSeek 安装根目录）。"
        if not doc_on_disk:
            doc_line += " 磁盘上未找到该文件 — 请确认打包时已将 docs/for-agents.md 放在 exe 同目录下。"
        not_ready = "索引未就绪 — 请让用户在 VideoSeek 中同步库后再搜索。"

    snapshot = {
        "base_url": base or api_base.replace("/api/v1", ""),
        "index_ready": index_ready,
        "index_stale": health.get("index_stale"),
        "model": health.get("model"),
        "provider": health.get("provider"),
        "search_mode_default": health.get("search_mode_default"),
        "video_count": health.get("video_count"),
        "vector_count": health.get("vector_count"),
        "saved_search_scope_mode": health.get("saved_search_scope_mode"),
        "search_timeout_sec": health.get("search_timeout_sec"),
        "search_timeout_precise_sec": health.get("search_timeout_precise_sec"),
        "agent_api_default_image_precision": health.get("agent_api_default_image_precision"),
        "ffmpeg_path": ffmpeg.get("ffmpeg_path"),
        "ffmpeg_available": ffmpeg.get("ffmpeg_available"),
    }

    parts = [
        intro,
        "",
        snapshot_title,
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        "",
        "capabilities:",
        _cap_lines(caps if isinstance(caps, dict) else {}),
        "",
        workflow_title,
        workflow,
        "",
        doc_line,
    ]
    if not index_ready:
        parts.extend(["", not_ready])
    return "\n".join(parts)


def build_agent_starter_payload(
    base_url: str,
    health: Dict[str, Any],
    *,
    locale: str = "zh",
) -> Dict[str, Any]:
    starter_text = build_agent_starter_text(base_url, health, locale=locale)
    return {
        "api_version": health.get("api_version", "1"),
        "ok": True,
        "starter_text": starter_text,
        "full_doc_rel": agent_doc_rel_path(),
        "full_doc_path": resolve_full_agent_doc_path(),
        "meta": {
            "locale": "en" if str(locale).lower().startswith("en") else "zh",
            "line_count": starter_text.count("\n") + 1,
            "doc_on_disk": resolve_full_agent_doc_path() is not None,
        },
    }
