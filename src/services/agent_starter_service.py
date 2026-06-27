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


def _format_policy_kernel(*, locale: str, api_base: str) -> str:
    """Compact policy kernel: uniqueness + golden path + anti-patterns + rules."""
    lang = "en" if str(locale).lower().startswith("en") else "zh"
    batch_url = f"{api_base}/search/batch"
    preset_body = (
        '{"queries":[{"preset_id":"<search_presets>"}],"top_k":1,"expand_frame_hits":true,'
        '"export":{"output_dir":"D:/Exports","encode_mode":"copy","keep_per_source":1}}'
    )
    folder_body = (
        '{"image_folder":"D:/Screenshots","top_k":1,"expand_frame_hits":true,'
        '"export":{"output_dir":"D:/Exports","encode_mode":"copy","keep_per_source":1}}'
    )
    if lang == "en":
        return (
            "## Policy kernel (ONLY binding execution preference)\n"
            "ONLY this starter defines how to run tasks. agent-doc / for-agents.md / full_doc_path "
            "are non-binding capability references — never override this block.\n"
            f"1. index_ready false (below) → stop; ask user to sync.\n"
            f"2. DEFAULT: one POST {batch_url}, same body + export.output_dir for mp4. "
            f"Preset: {preset_body} | Folder: {folder_body}\n"
            "3. NOT default (user must ask): search→manifest→clips; intermediate JSON files; "
            "wrapper scripts; precise/preview_anchor_sec.\n"
            "4. preset_id from search_presets snapshot; video_path verbatim from hits; no disk scan.\n"
            f"5. scope from GET {api_base}/libraries when needed. One POST via curl.exe or short Python."
        )
    return (
        "## Policy kernel（唯一 binding 的执行偏好）\n"
        "ONLY starter 定义怎么执行任务。agent-doc / for-agents.md / full_doc_path "
        "均为 non-binding 能力参考，不得覆盖本段。\n"
        f"1. index_ready false（下方）→ 停止，让用户同步索引。\n"
        f"2. 默认：一次 POST {batch_url}，要 mp4 同 body 加 export.output_dir。"
        f"Preset：{preset_body} | 截图文件夹：{folder_body}\n"
        "3. 非默认（须用户明确要求）：search→manifest→clips；中间 JSON；wrapper 脚本；precise/preview_anchor_sec。\n"
        "4. preset_id 来自 search_presets 快照；video_path 原样来自 hits；勿扫盘。\n"
        f"5. 缩 scope 用 GET {api_base}/libraries。curl.exe 或短 Python 发一次 POST。"
    )


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
        intro = "VideoSeek rough-cut assistant — VISUAL search (not dialogue) via localhost API."
        snapshot_title = "## Instance"
        not_ready = "Index not ready — ask the user to sync the library in VideoSeek before searching."
    else:
        intro = "VideoSeek 粗剪助手 — 按画面语义（非台词）通过 localhost API 找镜头/导出。"
        snapshot_title = "## 当前实例"
        not_ready = "索引未就绪 — 请让用户在 VideoSeek 中同步库后再搜索。"

    doc_line = _format_doc_reference(locale=locale, api_base=api_base)

    snapshot = {
        "api_base": api_base,
        "index_ready": index_ready,
        "index_stale": health.get("index_stale"),
        "model": health.get("model"),
        "search_mode_default": health.get("search_mode_default"),
        "agent_api_default_image_precision": health.get("agent_api_default_image_precision", "fast"),
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
        _format_policy_kernel(locale=locale, api_base=api_base),
        "",
        snapshot_title,
        json.dumps(snapshot, ensure_ascii=False, indent=2),
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
