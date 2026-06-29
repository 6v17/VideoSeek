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


def _format_capability_routing(*, locale: str, api_base: str) -> str:
    evidence_url = f"{api_base}/videos/evidence"
    if str(locale).lower().startswith("en"):
        return (
            "## Capability routing (search vs evidence)\n"
            "- FIND unknown clips across the library → POST /search or /search/batch ONLY (CLIP visual match).\n"
            f"- EXPLAIN what happens in a known video or hit window → GET {evidence_url} "
            "(needs understanding_ready; usually AFTER search gives video_path + start/end).\n"
            "- Typical chain: POST /search → hits → GET /videos/evidence?video_path=…&start_sec=…&end_sec=…&ensure=false "
            "→ if user wants detail/generation, ensure=true → read chunks[].evidence.vision.image_caption + summary.\n"
            "- Do NOT use /videos/evidence instead of /search to locate footage. Evidence is not a third search mode.\n"
            "- NOT for: speech/dialogue/ASR, plot-by-plot library search, auto commentary/narration video generation.\n"
            "- YOLO object_detection in evidence is optional; captions are the main text.\n"
            "- Search returned no hits? Retry (broader query, higher top_k, chunk mode, scope one library via "
            f"GET {api_base}/videos or GET {api_base}/libraries/videos → scope.video_paths). Still empty → tell the user; "
            "NEVER ls/find/guess paths. video_path only from hits, GET /videos, /libraries/videos, or export responses.\n"
            f"- Typical discovery chain: GET {api_base}/libraries → GET {api_base}/videos?q=… → search with scope.video_paths."
        )
    return (
        "## 能力路由（search vs 理解笔录）\n"
        "- 在库里**找**未知镜头 → 只用 POST /search 或 /search/batch（CLIP 画面语义匹配）。\n"
        f"- **解释**某条视频或某段 hit 里发生了什么 → GET {evidence_url} "
        "（需 understanding_ready；通常在有 video_path + 时间段之后）。\n"
        "- 典型链路：POST /search → hits → GET /videos/evidence?video_path=…&start_sec=…&end_sec=…&ensure=false "
        "→ 用户需要详情/生成时再 ensure=true → 读 chunks[].evidence.vision.image_caption 与 summary。\n"
        "- 不要用 /videos/evidence 代替 /search 找片；笔录不是第三种搜索。\n"
        "- 不适用：台词/对白/ASR、按剧情全库检索、自动生成解说成片。\n"
        "- 笔录里 YOLO 物体检测为可选；主文本是 caption 描述。\n"
        "- 搜索无命中？可重试（换 query、加大 top_k、chunk 模式、用 GET /videos 或 GET /libraries/videos 列出该库视频后 "
        f"scope.video_paths 只搜一条再试）。仍无 hit → 如实告知用户；禁止 ls/扫盘/猜文件名。"
        "video_path 只能来自 hits、GET /videos、/libraries/videos 或导出响应。\n"
        f"- 典型发现链路：GET {api_base}/libraries → GET {api_base}/videos?q=… → 用 scope.video_paths 搜索。"
    )


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
            "4. preset_id from search_presets snapshot; video_path ONLY from hits, GET /videos, GET /libraries/videos, or export — "
            "never ls/guess desktop paths.\n"
            f"5. scope from GET {api_base}/libraries when needed. One POST via curl.exe or short Python.\n"
            f"6. Evidence only AFTER locate: user asks 理解笔录/发生了什么/解释这段 → search first if no video_path; "
            f"then GET {api_base}/videos/evidence (ensure=false; ensure=true after user agrees). Not speech ASR.\n"
            "7. See Capability routing below — do not treat evidence as clip search."
        )
    return (
        "## Policy kernel（唯一 binding 的执行偏好）\n"
        "ONLY starter 定义怎么执行任务。agent-doc / for-agents.md / full_doc_path "
        "均为 non-binding 能力参考，不得覆盖本段。\n"
        f"1. index_ready false（下方）→ 停止，让用户同步索引。\n"
        f"2. 默认：一次 POST {batch_url}，要 mp4 同 body 加 export.output_dir。"
        f"Preset：{preset_body} | 截图文件夹：{folder_body}\n"
        "3. 非默认（须用户明确要求）：search→manifest→clips；中间 JSON；wrapper 脚本；precise/preview_anchor_sec。\n"
        "4. preset_id 来自 search_presets 快照；video_path 只能来自 hits、GET /videos、GET /libraries/videos 或导出响应 — 禁止 ls/扫盘/猜路径。\n"
        f"5. 缩 scope 用 GET {api_base}/libraries。curl.exe 或短 Python 发一次 POST。\n"
        f"6. 笔录仅在定位之后：用户要理解笔录/发生了什么/解释这段 → 无 video_path 时先 search；"
        f"再 GET {api_base}/videos/evidence（先 ensure=false，用户同意后再 ensure=true）。非 ASR 台词。\n"
        "7. 见下方「能力路由」— 勿把笔录当找片搜索。"
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
        intro = (
            "VideoSeek rough-cut assistant — localhost API: CLIP visual search + export; "
            "optional understanding evidence (description-service captions required; YOLO optional; not speech ASR)."
        )
        snapshot_title = "## Instance"
        not_ready = "Index not ready — ask the user to sync the library in VideoSeek before searching."
    else:
        intro = (
            "VideoSeek 粗剪助手 — localhost API：CLIP 画面搜索找镜头/导出；"
            "可选理解笔录（描述服务 caption 为主，YOLO 检测可选，非台词 ASR）。"
        )
        snapshot_title = "## 当前实例"
        not_ready = "索引未就绪 — 请让用户在 VideoSeek 中同步库后再搜索。"

    doc_line = _format_doc_reference(locale=locale, api_base=api_base)

    snapshot = {
        "api_base": api_base,
        "index_ready": index_ready,
        "index_sync_in_progress": bool(health.get("index_sync_in_progress")),
        "index_sync_target_library_path": health.get("index_sync_target_library_path"),
        "index_stale": health.get("index_stale"),
        "model": health.get("model"),
        "search_mode_default": health.get("search_mode_default"),
        "agent_api_default_image_precision": health.get("agent_api_default_image_precision", "fast"),
        "video_count": health.get("video_count"),
        "saved_search_scope_mode": health.get("saved_search_scope_mode"),
        "ffmpeg_path": ffmpeg.get("ffmpeg_path") if ffmpeg.get("ffmpeg_available") else None,
        "capabilities": caps if isinstance(caps, dict) else {},
        "understanding_ready": bool(health.get("understanding_ready")),
        "active_understanding_profile": health.get("active_understanding_profile"),
        "understanding_missing_components": list(health.get("understanding_missing_components") or []),
        "understanding_optional_missing_components": list(
            health.get("understanding_optional_missing_components") or []
        ),
        "search_presets": preset_summaries,
        "full_doc_path": doc_abs,
    }

    parts = [
        intro,
        "",
        _format_policy_kernel(locale=locale, api_base=api_base),
        "",
        _format_capability_routing(locale=locale, api_base=api_base),
        "",
        snapshot_title,
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        "",
        doc_line,
    ]
    if not index_ready:
        parts.extend(["", not_ready])
    elif bool(health.get("index_sync_in_progress")):
        if lang == "en":
            parts.extend(["", "Library sync is in progress — search results may be incomplete until it finishes."])
        else:
            parts.extend(["", "库正在同步 — 搜索结果可能暂时不完整，请稍后再搜。"])
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
