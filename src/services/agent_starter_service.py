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


def read_agent_doc_content() -> Optional[str]:
    """Full markdown text of docs/for-agents.md when present beside the install."""
    doc_path = resolve_full_agent_doc_path()
    if not doc_path:
        return None
    with open(doc_path, encoding="utf-8") as handle:
        return handle.read()


def _format_doc_reference(*, locale: str, api_base: str) -> str:
    """One-line pointer to full API doc over HTTP (no disk scan)."""
    lang = "en" if str(locale).lower().startswith("en") else "zh"
    doc_url = f"{api_base}/agent-doc?format=text"
    if lang == "en":
        return f"Full API fields: GET {doc_url} — do not scan the disk."
    return f"查 API 字段：GET {doc_url}（勿扫盘）。"


def _search_preset_summaries(*, limit: int = 24) -> list[Dict[str, Any]]:
    """Compact preset list for paste block (live instance, not static md)."""
    try:
        from src.web.agent_api import list_agent_search_presets

        payload = list_agent_search_presets()
        presets = payload.get("presets") or []
    except Exception:
        return []
    summaries: list[Dict[str, Any]] = []
    for item in presets:
        if not isinstance(item, dict):
            continue
        preset_id = str(item.get("id", "") or "").strip()
        if not preset_id:
            continue
        entry: Dict[str, Any] = {
            "id": preset_id,
            "name": str(item.get("name", "") or "").strip(),
        }
        query = str(item.get("query", "") or "").strip()
        if query:
            entry["query"] = query
        summary = str(item.get("summary", "") or "").strip()
        if summary:
            entry["summary"] = summary
        ref_count = item.get("reference_image_count")
        if ref_count:
            entry["reference_image_count"] = int(ref_count)
        summaries.append(entry)
        if len(summaries) >= max(1, int(limit)):
            break
    return summaries


def build_agent_starter_text(
    base_url: str,
    health: Dict[str, Any],
    *,
    locale: str = "zh",
    preset_summaries: Optional[list[Dict[str, Any]]] = None,
) -> str:
    """Build paste block: intro + live snapshot + preset-first workflow."""
    lang = "en" if str(locale).lower().startswith("en") else "zh"
    base = str(base_url or "").rstrip("/")
    api_base = f"{base}/api/v1" if base else "http://127.0.0.1:8765/api/v1"
    doc_abs = resolve_full_agent_doc_path()
    if preset_summaries is None:
        preset_summaries = _search_preset_summaries()

    caps = health.get("capabilities") or {}
    ffmpeg = health.get("ffmpeg") or {}
    index_ready = bool(health.get("index_ready"))

    if lang == "en":
        intro = (
            "You are VideoSeek's rough-cut assistant on this PC: find shots by VISUAL meaning "
            "(not dialogue) via localhost API. Do not rebuild indexes or change settings unless asked."
        )
        snapshot_title = "## Instance"
        workflow_title = "## Workflow"
        workflow = (
            "1. If index_ready is false (below), stop and ask the user to sync the library.\n"
            "2. GET {api}/libraries — scope.library_paths from library_path; do not guess folders.\n"
            "3. Map each script beat to search_presets id when possible; else write inline query "
            "in the same style as preset query/summary (visible shot, not dialogue).\n"
            "4. POST {api}/search/batch — use preset_id (preferred) or query; expand_frame_hits=true.\n"
            "5. Export only if needed: export/manifest → export/clips/batch (encode_mode=copy, paths outside libraries)."
        ).format(api=api_base)
        doc_line = _format_doc_reference(locale=locale, api_base=api_base)
        not_ready = "Index not ready — ask the user to sync the library in VideoSeek before searching."
    else:
        intro = (
            "你是本机 VideoSeek 粗剪助手：通过 localhost API 按画面语义找镜头（非台词），代用户搜索/导出。"
            "勿重建索引或改设置，除非用户明确要求。"
        )
        snapshot_title = "## 当前实例"
        workflow_title = "## 流程"
        workflow = (
            "1. 下方 index_ready 为 false 则停止，让用户在 VideoSeek 同步索引。\n"
            "2. GET {api}/libraries — scope.library_paths 用返回的 library_path，勿猜目录。\n"
            "3. 每条脚本句优先映射 search_presets 的 id；配不上则按 preset 的 query/summary 风格写 inline query（可见镜头，非台词）。\n"
            "4. POST {api}/search/batch — 优先 preset_id；expand_frame_hits=true；图搜 precise。\n"
            "5. 需导出时分步：export/manifest → export/clips/batch（copy，output 勿在库内）。"
        ).format(api=api_base)
        doc_line = _format_doc_reference(locale=locale, api_base=api_base)
        not_ready = "索引未就绪 — 请让用户在 VideoSeek 中同步库后再搜索。"

    snapshot = {
        "api_base": api_base,
        "index_ready": index_ready,
        "index_stale": health.get("index_stale"),
        "model": health.get("model"),
        "search_mode_default": health.get("search_mode_default"),
        "video_count": health.get("video_count"),
        "saved_search_scope_mode": health.get("saved_search_scope_mode"),
        "ffmpeg_path": ffmpeg.get("ffmpeg_path") if ffmpeg.get("ffmpeg_available") else None,
        "capabilities": caps if isinstance(caps, dict) else {},
        "search_presets": preset_summaries,
        "full_doc_path": doc_abs,
    }

    parts = [
        intro,
        "",
        snapshot_title,
        json.dumps(snapshot, ensure_ascii=False, indent=2),
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
    preset_summaries = _search_preset_summaries()
    starter_text = build_agent_starter_text(
        base_url, health, locale=locale, preset_summaries=preset_summaries
    )
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
            "search_preset_count": len(preset_summaries),
        },
    }


def build_agent_doc_payload(*, api_version: str = "1") -> Dict[str, Any]:
    doc_rel = agent_doc_rel_path()
    doc_abs = resolve_full_agent_doc_path()
    content = read_agent_doc_content()
    if content is None:
        raise FileNotFoundError(doc_rel)
    return {
        "api_version": api_version,
        "ok": True,
        "content": content,
        "full_doc_rel": doc_rel,
        "full_doc_path": doc_abs,
        "meta": {
            "line_count": content.count("\n") + 1,
            "byte_size": len(content.encode("utf-8")),
            "doc_on_disk": True,
        },
    }
