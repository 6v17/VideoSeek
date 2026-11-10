"""Stdio MCP adapter for the local Agent API.

The desktop app keeps serving HTTP on 127.0.0.1. This process only forwards
six tools and two resources. It does not search, index, or export by itself.

Cursor config (cwd is the VideoSeek repo)::

    python -m src.web.mcp_server
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

PROTOCOL_VERSION = "2024-11-05"
_SERVER_NAME = "videoseek"
_MAX_FRAME_ITEMS = 16
_MAX_EXPORT_ITEMS = 64
_MAX_SEARCH_QUERIES = 64
# Desktop accepts the job and returns; indexing continues in the app.
_SYNC_ACCEPT_TIMEOUT_SEC = 60
# add/refresh may scan folders before they accept.
_SCAN_ACCEPT_TIMEOUT_SEC = 180
_TIMELINE_TIMEOUT_HINT = (
    "timeline 输出上限 60 秒，超时返回 engine_busy；重试前减少 items 或改 output=manifest。"
)

_PATH_RULE = (
    "video_path 和 library_path 必须原样来自本次对话里更早的工具结果，或用户明确给出的绝对路径。"
    "不要按显示名猜测文件名。写出的文件不要放进已索引的库目录。"
)

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_libraries",
        "description": (
            "列出画面库、库内已索引视频，或字幕库。"
            "先用 kind=libraries 看有哪些库，再用 kind=videos 取 video_path。"
            "字幕用 kind=subtitle_libraries / subtitle_videos。"
            + _PATH_RULE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["libraries", "videos", "subtitle_libraries", "subtitle_videos"],
                },
                "library_path": {"type": "string"},
                "q": {"type": "string"},
                "video_id": {"type": "string"},
                "ready_only": {"type": "boolean"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
            "required": ["kind"],
            "additionalProperties": False,
        },
    },
    {
        "name": "sync_library",
        "description": (
            "登记库或同步索引。action=add：把已有文件夹登记为画面库并索引；"
            "include：只索引给出的视频文件；refresh：只重扫视频列表，不索引；"
            "sync：同步整库，或只同步 video_ids / video_paths。"
            "四条都是交给桌面开始后就返回，不会等到索引结束。add 和 refresh 可能要扫盘，比 sync 慢。"
            + _PATH_RULE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "include", "refresh", "sync"]},
                "library_path": {"type": "string"},
                "video_paths": {"type": "array", "items": {"type": "string"}},
                "video_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search",
        "description": (
            "在已索引视频里搜索。一次用 query 或 preset_id；多条用 queries；"
            "或用 image_folder 把文件夹里的图片各搜一次。"
            "search_kind 为 visual（默认画面）、dialogue（台词）或 tags。"
            "结果是路径和时间，不是画面。要看画面再调用 extract_frames。"
            + _PATH_RULE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "queries": {"type": "array", "items": {"type": "object"}},
                "preset_id": {"type": "string"},
                "query_type": {"type": "string", "enum": ["text", "image_path"]},
                "image_path": {"type": "string"},
                "image_folder": {"type": "string"},
                "search_kind": {"type": "string", "enum": ["visual", "dialogue", "tags"]},
                "top_k": {"type": "integer"},
                "mode": {"type": "string", "enum": ["frame", "chunk"]},
                "min_score": {"type": "number"},
                "search_precision_mode": {"type": "string", "enum": ["fast", "precise"]},
                "match_mode": {"type": "string", "enum": ["exact", "fuzzy", "auto"]},
                "scope": {
                    "type": "object",
                    "properties": {
                        "library_paths": {"type": "array", "items": {"type": "string"}},
                        "video_paths": {"type": "array", "items": {"type": "string"}},
                        "use_saved_scope": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                "text_enhance": {"type": "boolean"},
                "video_discovery_enabled": {"type": "boolean"},
                "preview_anchor_sec": {"type": "number"},
                "locate_anchor_score": {"type": "number"},
                "locate_score_margin": {"type": "number"},
                "continue_on_error": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "extract_frames",
        "description": (
            "按 video_path 和 time_sec 抽 JPEG，一次 1 到 16 帧。"
            "video_path 必须来自 search 或 list_libraries。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": _MAX_FRAME_ITEMS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "video_path": {"type": "string"},
                            "time_sec": {"type": "number"},
                            "max_edge": {"type": "integer"},
                        },
                        "required": ["video_path", "time_sec"],
                        "additionalProperties": False,
                    },
                },
                "max_edge": {"type": "integer"},
                "continue_on_error": {"type": "boolean"},
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    },
    {
        "name": "export_clips",
        "description": (
            "导出 mp4 片段。一条可以用 output_dir；多条时每条都要自己的 output_path。"
            "encode_mode 用 copy（快）或 original（切点更准）。"
            + _PATH_RULE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": _MAX_EXPORT_ITEMS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "video_path": {"type": "string"},
                            "start_sec": {"type": "number"},
                            "end_sec": {"type": "number"},
                            "output_path": {"type": "string"},
                            "output_dir": {"type": "string"},
                            "silent": {"type": "boolean"},
                            "encode_mode": {"type": "string", "enum": ["copy", "original"]},
                        },
                        "required": ["video_path", "start_sec", "end_sec"],
                        "additionalProperties": False,
                    },
                },
                "output_dir": {"type": "string"},
                "silent": {"type": "boolean"},
                "encode_mode": {"type": "string", "enum": ["copy", "original"]},
                "continue_on_error": {"type": "boolean"},
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    },
    {
        "name": "export_timeline",
        "description": (
            "output=timeline 时把多段写成剪映草稿、达芬奇 FCPXML 或 Premiere XML。"
            + _TIMELINE_TIMEOUT_HINT
            + "output=manifest 时只生成清单 JSON，不写剪辑工程。"
            "片段的路径和时间必须来自 search。"
            + _PATH_RULE
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "output": {"type": "string", "enum": ["timeline", "manifest"]},
                "format": {"type": "string", "enum": ["jianying", "fcpxml", "fcp7_xml"]},
                "items": {"type": "array", "items": {"type": "object"}},
                "project": {"type": "string"},
                "write_path": {"type": "string"},
                "output_dir": {"type": "string"},
                "drafts_dir": {"type": "string"},
                "draft_name": {"type": "string"},
                "sources": {"type": "array", "items": {"type": "object"}},
                "keep_per_source": {"type": "integer"},
                "dedupe": {"type": "boolean"},
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    },
]

_RESOURCES: list[dict[str, str]] = [
    {
        "uri": "videoseek://status",
        "name": "status",
        "description": "索引是否就绪、画面和台词能不能搜、批量上限和搜索超时。开始搜索前先读一次。",
        "mimeType": "application/json",
    },
    {
        "uri": "videoseek://presets",
        "name": "presets",
        "description": "搜索预设的 id 和名称。要用某个预设时，把 id 传给 search 的 preset_id。",
        "mimeType": "application/json",
    },
]

_SEARCH_FIELDS = (
    "query",
    "preset_id",
    "query_type",
    "image_path",
    "search_kind",
    "top_k",
    "mode",
    "min_score",
    "search_precision_mode",
    "match_mode",
    "scope",
    "text_enhance",
    "video_discovery_enabled",
    "preview_anchor_sec",
    "locate_anchor_score",
    "locate_score_margin",
)
_BATCH_FIELDS = (
    "queries",
    "image_folder",
    "search_kind",
    "top_k",
    "mode",
    "min_score",
    "search_precision_mode",
    "video_discovery_enabled",
    "text_enhance",
    "continue_on_error",
    "scope",
)


class AgentApiUnreachable(RuntimeError):
    """The desktop Agent API is not accepting connections."""


class AgentHttpClient:
    """Loopback HTTP client. Tests replace request_json."""

    def __init__(self, base_url: str):
        self.base_url = str(base_url).rstrip("/")

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        timeout: float = 60,
    ) -> tuple[int, Any]:
        url = self.base_url + path
        if query:
            pairs = []
            for key, value in query.items():
                if value is None:
                    continue
                if isinstance(value, bool):
                    text = "true" if value else "false"
                else:
                    text = str(value)
                pairs.append((key, text))
            if pairs:
                url = url + "?" + urllib.parse.urlencode(pairs)
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(_drop_none(body), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = int(response.status)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = int(exc.code)
        except urllib.error.URLError as exc:
            raise AgentApiUnreachable(
                "连不上本机 VideoSeek 接口（"
                + self.base_url
                + "）。请打开 VideoSeek，搜索接口选「本机 Agent API」并保存。"
            ) from exc
        if not raw:
            return status, {}
        try:
            return status, json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return status, {"ok": False, "error": {"code": "invalid_response", "message": raw.decode("utf-8", "replace")}}


def default_api_base() -> str:
    explicit = str(os.environ.get("VIDEOSEEK_API_BASE", "") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = str(os.environ.get("VIDEOSEEK_AGENT_API_HOST", "127.0.0.1") or "127.0.0.1").strip()
    port = str(os.environ.get("VIDEOSEEK_AGENT_API_PORT", "8765") or "8765").strip()
    return f"http://{host}:{port}"


def repo_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def cursor_mcp_config() -> dict[str, Any]:
    """Cursor mcp.json fragment. The app must stay open with the local API on."""
    return {
        "mcpServers": {
            "videoseek": {
                "command": sys.executable,
                "args": ["-m", "src.web.mcp_server"],
                "cwd": repo_root(),
            }
        }
    }


def cursor_mcp_config_text() -> str:
    return json.dumps(cursor_mcp_config(), ensure_ascii=False, indent=2)


def handle_message(message: Mapping[str, Any], api: AgentHttpClient) -> dict[str, Any] | None:
    """Return a JSON-RPC response, or None for notifications."""
    if "id" not in message:
        return None
    request_id = message.get("id")
    method = str(message.get("method") or "")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    try:
        result = _dispatch(method, params, api)
    except AgentApiUnreachable as exc:
        if method == "tools/call":
            result = _tool_error(str(exc))
        else:
            return _rpc_error(request_id, -32000, str(exc))
    except ValueError as exc:
        return _rpc_error(request_id, -32602, str(exc))
    if result is None:
        return _rpc_error(request_id, -32601, f"Method not found: {method}")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(api: AgentHttpClient, stdin, stdout) -> None:
    for line in stdin:
        text = str(line).strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            _write(stdout, _rpc_error(None, -32700, "Parse error"))
            continue
        if not isinstance(message, dict):
            _write(stdout, _rpc_error(None, -32600, "Invalid request"))
            continue
        response = handle_message(message, api)
        if response is not None:
            _write(stdout, response)


def main() -> int:
    serve(AgentHttpClient(default_api_base()), sys.stdin, sys.stdout)
    return 0


def _dispatch(method: str, params: Mapping[str, Any], api: AgentHttpClient) -> Any | None:
    if method == "initialize":
        client_version = str(params.get("protocolVersion") or PROTOCOL_VERSION)
        return {
            "protocolVersion": client_version or PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False}},
            "serverInfo": {"name": _SERVER_NAME, "version": "1"},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": _TOOLS}
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        return _call_tool(name, arguments, api)
    if method == "resources/list":
        return {"resources": _RESOURCES}
    if method == "resources/templates/list":
        return {"resourceTemplates": []}
    if method == "resources/read":
        return _read_resource(str(params.get("uri") or ""), api)
    return None


def _call_tool(name: str, arguments: Mapping[str, Any], api: AgentHttpClient) -> dict[str, Any]:
    try:
        status, payload = _invoke_tool(name, arguments, api)
    except AgentApiUnreachable:
        raise
    except ValueError as exc:
        return _tool_error(str(exc))
    failed = status >= 400 or (isinstance(payload, dict) and payload.get("ok") is False)
    return _tool_result(payload, is_error=failed)


def _invoke_tool(name: str, arguments: Mapping[str, Any], api: AgentHttpClient) -> tuple[int, Any]:
    if name == "list_libraries":
        return _list_libraries(arguments, api)
    if name == "sync_library":
        return _sync_library(arguments, api)
    if name == "search":
        return _search(arguments, api)
    if name == "extract_frames":
        return _extract_frames(arguments, api)
    if name == "export_clips":
        return _export_clips(arguments, api)
    if name == "export_timeline":
        return _export_timeline(arguments, api)
    raise ValueError(f"Unknown tool: {name}")


def _list_libraries(arguments: Mapping[str, Any], api: AgentHttpClient) -> tuple[int, Any]:
    kind = str(arguments.get("kind") or "")
    query = {
        "library_path": arguments.get("library_path"),
        "video_id": arguments.get("video_id"),
        "q": arguments.get("q"),
        "ready_only": arguments.get("ready_only"),
        "limit": arguments.get("limit"),
        "offset": arguments.get("offset"),
    }
    if kind == "libraries":
        return api.request_json("GET", "/api/v1/libraries", timeout=60)
    if kind == "videos":
        return api.request_json("GET", "/api/v1/videos", query=query, timeout=60)
    if kind == "subtitle_libraries":
        return api.request_json("GET", "/api/v1/subtitle-libraries", timeout=60)
    if kind == "subtitle_videos":
        return api.request_json("GET", "/api/v1/subtitle-libraries/videos", query=query, timeout=60)
    raise ValueError("kind must be libraries, videos, subtitle_libraries, or subtitle_videos.")


def _sync_library(arguments: Mapping[str, Any], api: AgentHttpClient) -> tuple[int, Any]:
    action = str(arguments.get("action") or "")
    library_path = arguments.get("library_path")
    video_paths = arguments.get("video_paths")
    video_ids = arguments.get("video_ids")
    if action == "add":
        if not str(library_path or "").strip():
            raise ValueError("add requires library_path.")
        return api.request_json(
            "POST",
            "/api/v1/libraries",
            body={"library_path": library_path},
            timeout=_SCAN_ACCEPT_TIMEOUT_SEC,
        )
    if action == "include":
        if not isinstance(video_paths, list) or not video_paths:
            raise ValueError("include requires video_paths.")
        return api.request_json(
            "POST",
            "/api/v1/libraries/include",
            body={"video_paths": video_paths},
            timeout=_SYNC_ACCEPT_TIMEOUT_SEC,
        )
    if action == "refresh":
        body = {"library_path": library_path} if library_path else {}
        return api.request_json(
            "POST",
            "/api/v1/libraries/refresh",
            body=body,
            timeout=_SCAN_ACCEPT_TIMEOUT_SEC,
        )
    if action == "sync":
        return api.request_json(
            "POST",
            "/api/v1/index/sync",
            body={"library_path": library_path, "video_ids": video_ids, "video_paths": video_paths},
            timeout=_SYNC_ACCEPT_TIMEOUT_SEC,
        )
    raise ValueError("action must be add, include, refresh, or sync.")


def _search(arguments: Mapping[str, Any], api: AgentHttpClient) -> tuple[int, Any]:
    queries = arguments.get("queries")
    image_folder = arguments.get("image_folder")
    batch = bool(image_folder) or isinstance(queries, list)
    if batch:
        if queries is not None and not isinstance(queries, list):
            raise ValueError("queries must be a list.")
        if isinstance(queries, list) and len(queries) > _MAX_SEARCH_QUERIES:
            raise ValueError(f"queries exceeds {_MAX_SEARCH_QUERIES}.")
        if not queries and not image_folder:
            raise ValueError("batch search needs queries or image_folder.")
        if arguments.get("query") or arguments.get("preset_id"):
            raise ValueError("use queries for a batch, or query / preset_id for one search.")
        body = {key: arguments.get(key) for key in _BATCH_FIELDS}
        return api.request_json("POST", "/api/v1/search/batch", body=body, timeout=1200)
    if not any(arguments.get(key) for key in ("query", "preset_id", "image_path")):
        raise ValueError("search needs query, preset_id, or image_path.")
    body = {key: arguments.get(key) for key in _SEARCH_FIELDS}
    return api.request_json("POST", "/api/v1/search", body=body, timeout=600)


def _extract_frames(arguments: Mapping[str, Any], api: AgentHttpClient) -> tuple[int, Any]:
    items = arguments.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items must contain 1 to 16 frames.")
    if len(items) > _MAX_FRAME_ITEMS:
        raise ValueError(f"items exceeds {_MAX_FRAME_ITEMS}.")
    for item in items:
        if not isinstance(item, dict) or not str(item.get("video_path") or "").strip():
            raise ValueError("each frame needs video_path and time_sec.")
        if item.get("time_sec") is None:
            raise ValueError("each frame needs video_path and time_sec.")
    if len(items) == 1:
        one = dict(items[0])
        if one.get("max_edge") is None and arguments.get("max_edge") is not None:
            one["max_edge"] = arguments.get("max_edge")
        return api.request_json("POST", "/api/v1/frames/extract", body=one, timeout=120)
    body = {
        "items": items,
        "max_edge": arguments.get("max_edge"),
        "continue_on_error": arguments.get("continue_on_error", True),
    }
    return api.request_json("POST", "/api/v1/frames/extract/batch", body=body, timeout=120)


def _export_clips(arguments: Mapping[str, Any], api: AgentHttpClient) -> tuple[int, Any]:
    items = arguments.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items must contain at least one clip.")
    if len(items) > _MAX_EXPORT_ITEMS:
        raise ValueError(f"items exceeds {_MAX_EXPORT_ITEMS}.")
    if len(items) == 1:
        item = dict(items[0])
        if not item.get("output_path") and not item.get("output_dir"):
            item["output_dir"] = arguments.get("output_dir")
        if arguments.get("silent") is not None and item.get("silent") is None:
            item["silent"] = arguments.get("silent")
        if arguments.get("encode_mode") and not item.get("encode_mode"):
            item["encode_mode"] = arguments.get("encode_mode")
        if not item.get("output_path") and not item.get("output_dir"):
            raise ValueError("a single clip needs output_path or output_dir.")
        return api.request_json("POST", "/api/v1/export/clip", body=item, timeout=1200)
    for item in items:
        if not isinstance(item, dict) or not str(item.get("output_path") or "").strip():
            raise ValueError("each clip in a batch needs its own output_path.")
    body = {
        "items": items,
        "silent": arguments.get("silent"),
        "encode_mode": arguments.get("encode_mode"),
        "continue_on_error": arguments.get("continue_on_error", True),
    }
    return api.request_json("POST", "/api/v1/export/clips/batch", body=body, timeout=1200)


def _export_timeline(arguments: Mapping[str, Any], api: AgentHttpClient) -> tuple[int, Any]:
    output = str(arguments.get("output") or "timeline")
    items = arguments.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items must contain at least one clip.")
    if output == "manifest":
        body = {
            "project": arguments.get("project") or "rough-cut",
            "items": items,
            "sources": arguments.get("sources"),
            "keep_per_source": arguments.get("keep_per_source"),
            "dedupe": arguments.get("dedupe"),
            "write_path": arguments.get("write_path"),
        }
        return api.request_json("POST", "/api/v1/export/manifest", body=body, timeout=45)
    if output != "timeline":
        raise ValueError("output must be timeline or manifest.")
    fmt = str(arguments.get("format") or "").strip()
    if fmt not in {"jianying", "fcpxml", "fcp7_xml"}:
        raise ValueError("timeline export needs format: jianying, fcpxml, or fcp7_xml.")
    body = {
        "format": fmt,
        "items": items,
        "project": arguments.get("project"),
        "write_path": arguments.get("write_path"),
        "output_dir": arguments.get("output_dir"),
        "drafts_dir": arguments.get("drafts_dir"),
        "draft_name": arguments.get("draft_name"),
    }
    status, payload = api.request_json("POST", "/api/v1/export/timeline", body=body, timeout=75)
    if _is_engine_busy(status, payload):
        raise ValueError(_TIMELINE_TIMEOUT_HINT)
    return status, payload


def _read_resource(uri: str, api: AgentHttpClient) -> dict[str, Any]:
    if uri == "videoseek://status":
        status, payload = api.request_json("GET", "/api/v1/health", timeout=60)
        if status < 400 and isinstance(payload, dict):
            payload = _slim_status(payload, api.base_url)
    elif uri == "videoseek://presets":
        _status, payload = api.request_json("GET", "/api/v1/search/presets", timeout=60)
    else:
        raise ValueError(f"Unknown resource: {uri}")
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": "application/json",
                "text": json.dumps(payload, ensure_ascii=False),
            }
        ]
    }


def _slim_status(payload: Mapping[str, Any], api_base_url: str) -> dict[str, Any]:
    capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
    team = payload.get("team") if isinstance(payload.get("team"), dict) else {}
    base = str(team.get("api_base_url") or "").strip() or api_base_url
    return {
        "ok": payload.get("ok"),
        "api_version": payload.get("api_version"),
        "ready": bool(payload.get("index_ready")),
        "chunk_index_ready": bool(capabilities.get("chunk_search")),
        "dialogue_index_ready": bool(payload.get("dialogue_index_ready")),
        "frame_search_ready": bool(capabilities.get("frame_search")),
        "limits": {
            "batch_search": payload.get("max_batch_queries"),
            "frames_per_call": payload.get("max_batch_frame_extract"),
            "timeout_sec": payload.get("search_timeout_sec"),
        },
        "api_base_url": base,
    }


def _is_engine_busy(status: int, payload: Any) -> bool:
    if status != 503 or not isinstance(payload, dict):
        return False
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or "") == "engine_busy"
    return False


def _tool_result(payload: Any, *, is_error: bool) -> dict[str, Any]:
    slim, images = _lift_images(payload)
    content: list[dict[str, Any]] = [
        {"type": "text", "text": json.dumps(slim, ensure_ascii=False, indent=2)}
    ]
    content.extend(images)
    result: dict[str, Any] = {"content": content}
    if is_error:
        result["isError"] = True
    return result


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _lift_images(payload: Any) -> tuple[Any, list[dict[str, str]]]:
    images: list[dict[str, str]] = []

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            copied: dict[str, Any] = {}
            for key, value in node.items():
                if key == "image_base64" and isinstance(value, str) and value:
                    images.append(
                        {
                            "type": "image",
                            "data": value,
                            "mimeType": str(node.get("mime") or "image/jpeg"),
                        }
                    )
                    copied[key] = "[image]"
                else:
                    copied[key] = walk(value)
            return copied
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(payload), images


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _write(stdout, payload: Mapping[str, Any]) -> None:
    stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    flush = getattr(stdout, "flush", None)
    if callable(flush):
        flush()


if __name__ == "__main__":
    raise SystemExit(main())
