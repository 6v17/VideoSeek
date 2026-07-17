"""Short paste-ready onboarding text for external agents (Cursor, Claude, scripts)."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from src.utils import get_resource_path

# Relative to VideoSeek install / repo root (same layout for dev and Nuitka output).
AGENT_DOC_REL = "docs/for-agents.md"
STARTER_PRESET_SNAPSHOT_LIMIT = 8


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
        return f"Fields / playbook: GET {doc_url} (§5) — do not scan the disk."
    return f"字段与 playbook：GET {doc_url}（§5）— 勿扫盘。"


def _search_preset_summaries(*, limit: int = STARTER_PRESET_SNAPSHOT_LIMIT) -> Tuple[List[Dict[str, Any]], int]:
    """Compact preset list for paste block (id/name only; full list via GET /search/presets)."""
    try:
        from src.web.agent_api import list_agent_search_presets

        payload = list_agent_search_presets()
        presets = payload.get("presets") or []
    except Exception:
        return [], 0
    total = 0
    summaries: List[Dict[str, Any]] = []
    for item in presets:
        if not isinstance(item, dict):
            continue
        preset_id = str(item.get("id", "") or "").strip()
        if not preset_id:
            continue
        total += 1
        if len(summaries) >= max(1, int(limit)):
            continue
        entry: Dict[str, Any] = {
            "id": preset_id,
            "name": str(item.get("name", "") or "").strip(),
        }
        if int(item.get("reference_image_count") or 0) > 0:
            entry["image"] = True
        summaries.append(entry)
    return summaries, total


def _build_user_capability_bullets(
    health: Dict[str, Any],
    *,
    preset_total: int = 0,
    locale: str = "zh",
) -> List[str]:
    """Plain-language capability lines for the first reply (≤6 bullets)."""
    lang = "en" if str(locale).lower().startswith("en") else "zh"
    caps = health.get("capabilities") if isinstance(health.get("capabilities"), dict) else {}
    ffmpeg = health.get("ffmpeg") if isinstance(health.get("ffmpeg"), dict) else {}
    bullets: List[str] = []

    if lang == "en":
        if not health.get("index_ready"):
            bullets.append("Index not ready — ask the user to sync libraries in VideoSeek first.")
        elif health.get("index_sync_in_progress"):
            bullets.append("Library sync running — results may be incomplete until it finishes.")
        else:
            n = health.get("video_count")
            bullets.append(
                f"Find shots by visual meaning in synced videos"
                + (f" (~{n} entries)." if n is not None else " (text or reference images).")
            )
        search_bits = []
        if caps.get("text_search"):
            search_bits.append("text")
        if caps.get("image_search"):
            search_bits.append("reference images / screenshot folders")
        if search_bits:
            bullets.append(f"Search: {' + '.join(search_bits)}; batch up to 64 queries.")
        if caps.get("export_clip") and ffmpeg.get("ffmpeg_available"):
            bullets.append("Export mp4 rough-cut clips (default fast copy).")
        if caps.get("video_evidence") and health.get("understanding_ready"):
            bullets.append("Optional: explain what happens in a found clip (captions, not dialogue/ASR).")
        if preset_total:
            bullets.append(
                f"{preset_total} search presets — snapshot shows up to {STARTER_PRESET_SNAPSHOT_LIMIT}; "
                "use GET /search/presets for all."
            )
        bullets.append("Not available: dialogue/ASR, plot reasoning, auto narration videos.")
        return bullets[:6]

    if not health.get("index_ready"):
        bullets.append("索引未就绪 — 请让用户在 VideoSeek 里先同步视频库。")
    elif health.get("index_sync_in_progress"):
        bullets.append("库正在同步 — 完成前搜索结果可能不完整。")
    else:
        n = health.get("video_count")
        bullets.append(
            "在已同步视频里按画面语义找镜头"
            + (f"（约 {n} 条）。" if n is not None else "（支持文字或参考图）。")
        )
    search_bits = []
    if caps.get("text_search"):
        search_bits.append("文字")
    if caps.get("image_search"):
        search_bits.append("参考图/截图文件夹")
    if search_bits:
        bullets.append(f"搜索：{' + '.join(search_bits)}；可一次批量最多 64 条。")
    if caps.get("export_clip") and ffmpeg.get("ffmpeg_available"):
        bullets.append("导出 mp4 粗剪片段（默认可快速 copy）。")
    if caps.get("video_evidence") and health.get("understanding_ready"):
        bullets.append("可选：解释某段画面在发生什么（caption，非台词/ASR）。")
    if preset_total:
        bullets.append(
            f"共 {preset_total} 个搜索预设 — 快照最多 {STARTER_PRESET_SNAPSHOT_LIMIT} 个，"
            "全量见 GET /search/presets。"
        )
    bullets.append("不支持：台词/ASR、全库剧情推理、自动解说成片。")
    return bullets[:6]


def _format_first_reply_instruction(
    health: Dict[str, Any],
    *,
    preset_total: int = 0,
    locale: str = "zh",
) -> str:
    """Tell the agent to explain capabilities to the user in plain language first."""
    lang = "en" if str(locale).lower().startswith("en") else "zh"
    bullets = _build_user_capability_bullets(health, preset_total=preset_total, locale=locale)
    bullet_lines = "\n".join(f"- {line}" for line in bullets)
    if lang == "en":
        return (
            "## First reply to the user (required)\n"
            "Your **first message** must briefly tell the user what you can help with **right now** "
            "(from the snapshot below; do not invent features). Include status, 3–6 example requests, "
            "and limits. Then ask what to find or export. Do not call the API silently first.\n"
            f"{bullet_lines}"
        )
    return (
        "## 读完请先告诉用户（必读）\n"
        "**第一条回复**须用通俗中文说明此刻能帮用户做什么（依据下方快照，勿编造）。"
        "含状态、3–6 条需求示例、不能做什么；再问想找/导出什么。**不要**先静默调 API。\n"
        f"{bullet_lines}"
    )


def _format_iron_rules(*, locale: str, api_base: str) -> str:
    doc_url = f"{api_base}/agent-doc?format=text"
    if str(locale).lower().startswith("en"):
        return (
            "## Three rules\n"
            "1. **Locate** clips → POST /search or /search/batch only. "
            "**Explain** a known hit → GET /videos/evidence after you have video_path + times; evidence is not a third search mode.\n"
            "2. **video_path** only from API responses (hits, GET /videos, export) — never ls/find/guess paths.\n"
            f"3. Optional scenarios, retries, manifest, chunk/image modes → GET {doc_url} §5 (non-binding; does not override Policy kernel)."
        )
    return (
        "## 三条铁律\n"
        "1. **找片** → 只用 POST /search 或 /search/batch；**解释**已有 hit → 在有 video_path + 时间段后用 GET /videos/evidence，笔录不是第三种搜索。\n"
        "2. **video_path** 只能来自 API 响应（hits、GET /videos、导出等）— 禁止 ls/扫盘/猜路径。\n"
        f"3. 可选场景、无命中重试、manifest、chunk/图搜等 → GET {doc_url} §5（non-binding，不覆盖 Policy kernel）。"
    )


def _format_policy_kernel(*, locale: str, api_base: str) -> str:
    """Compact binding execution preference."""
    lang = "en" if str(locale).lower().startswith("en") else "zh"
    batch_url = f"{api_base}/search/batch"
    preset_body = (
        '{"queries":[{"preset_id":"<id from snapshot>"}],"top_k":1,"expand_frame_hits":true,'
        '"export":{"output_dir":"D:/Exports","encode_mode":"copy","keep_per_source":1}}'
    )
    folder_body = (
        '{"image_folder":"D:/Screenshots","top_k":1,"expand_frame_hits":true,'
        '"export":{"output_dir":"D:/Exports","encode_mode":"copy","keep_per_source":1}}'
    )
    if lang == "en":
        return (
            "## Policy kernel (ONLY binding)\n"
            f"1. index_ready false → stop; ask user to sync.\n"
            f"2. DEFAULT: one POST {batch_url} + export.output_dir for mp4. "
            f"Preset: {preset_body} | Folder: {folder_body}\n"
            "3. preset_id from snapshot or GET /search/presets; video_path only from API — never guess paths.\n"
            "4. Non-default (user must ask): manifest, precise/preview_anchor_sec, intermediate JSON files.\n"
            f"5. Scope: GET {api_base}/libraries / GET {api_base}/videos when needed."
        )
    return (
        "## Policy kernel（唯一 binding）\n"
        f"1. index_ready false → 停止，让用户同步索引。\n"
        f"2. 默认：一次 POST {batch_url}，要 mp4 同 body 加 export.output_dir。"
        f"Preset：{preset_body} | 截图文件夹：{folder_body}\n"
        "3. preset_id 来自快照或 GET /search/presets；video_path 只来自 API — 禁止猜路径。\n"
        "4. 非默认（须用户要求）：manifest、precise/preview_anchor_sec、中间 JSON 文件。\n"
        f"5. 缩 scope：GET {api_base}/libraries / GET {api_base}/videos。"
    )


def build_agent_starter_text(
    base_url: str,
    health: Dict[str, Any],
    *,
    locale: str = "zh",
    preset_summaries: Optional[List[Dict[str, Any]]] = None,
    preset_total: Optional[int] = None,
) -> str:
    """Build paste block: first reply + policy + compact snapshot."""
    lang = "en" if str(locale).lower().startswith("en") else "zh"
    base = str(base_url or "").rstrip("/")
    api_base = f"{base}/api/v1" if base else "http://127.0.0.1:8765/api/v1"
    if preset_summaries is None or preset_total is None:
        preset_summaries, preset_total = _search_preset_summaries()

    caps = health.get("capabilities") or {}
    index_ready = bool(health.get("index_ready"))

    if lang == "en":
        intro = (
            "VideoSeek — localhost CLIP visual search + export; optional understanding evidence; "
            "optional dialogue search via search_kind=dialogue when dialogue_index_ready."
        )
        snapshot_title = "## Instance"
        not_ready = "Index not ready — ask the user to sync in VideoSeek before searching."
    else:
        intro = (
            "VideoSeek — 本机 CLIP 画面搜索 + 导出；可选理解笔录；"
            "台词检索在 dialogue_index_ready 时用 search_kind=dialogue。"
        )
        snapshot_title = "## 当前实例"
        not_ready = "索引未就绪 — 请让用户在 VideoSeek 中同步后再搜索。"

    snapshot: Dict[str, Any] = {
        "api_base": api_base,
        "index_ready": index_ready,
        "index_sync_in_progress": bool(health.get("index_sync_in_progress")),
        "video_count": health.get("video_count"),
        "search_mode_default": health.get("search_mode_default"),
        "capabilities": caps if isinstance(caps, dict) else {},
        "understanding_ready": bool(health.get("understanding_ready")),
        "dialogue_index_ready": bool(health.get("dialogue_index_ready")),
        "dialogue_indexed_videos": health.get("dialogue_indexed_videos"),
        "search_presets": preset_summaries,
    }
    if preset_total > len(preset_summaries):
        snapshot["search_presets_total"] = preset_total

    parts = [
        intro,
        "",
        _format_first_reply_instruction(health, preset_total=preset_total, locale=locale),
        "",
        _format_policy_kernel(locale=locale, api_base=api_base),
        "",
        _format_iron_rules(locale=locale, api_base=api_base),
        "",
        snapshot_title,
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        "",
        _format_doc_reference(locale=locale, api_base=api_base),
    ]
    if not index_ready:
        parts.extend(["", not_ready])
    elif bool(health.get("index_sync_in_progress")):
        if lang == "en":
            parts.extend(["", "Library sync in progress — results may be incomplete."])
        else:
            parts.extend(["", "库正在同步 — 结果可能暂时不完整。"])
    return "\n".join(parts)


def build_agent_starter_payload(
    base_url: str,
    health: Dict[str, Any],
    *,
    locale: str = "zh",
) -> Dict[str, Any]:
    preset_summaries, preset_total = _search_preset_summaries()
    starter_text = build_agent_starter_text(
        base_url,
        health,
        locale=locale,
        preset_summaries=preset_summaries,
        preset_total=preset_total,
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
            "search_preset_count": preset_total,
            "search_preset_snapshot_count": len(preset_summaries),
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
