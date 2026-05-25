"""Localhost Agent API (v1): health + visual search only."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any, Dict, List, Optional

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError as exc:
    FastAPI = None
    HTTPException = None
    JSONResponse = None
    BaseModel = object
    Field = lambda *args, **kwargs: None
    uvicorn = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.domain.search_hit import SearchHit
from src.services.library_service import get_global_index_state, list_libraries
from src.services.search_service import load_chunk_search_assets, load_search_assets, run_chunk_search, run_search
from src.storage.config_store import get_active_embedding_spec, get_search_mode, get_search_top_k

logger = get_logger("agent_api")

API_VERSION = "1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SEARCH_TIMEOUT_SEC = 120.0
MAX_CONCURRENT_SEARCHES = 2

_search_semaphore = threading.Semaphore(MAX_CONCURRENT_SEARCHES)


class AgentSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    query_type: str = "text"
    top_k: Optional[int] = None
    mode: Optional[str] = None
    min_score: Optional[float] = None
    client_request_id: Optional[str] = None


def _normalize_mode(mode: Optional[str]) -> str:
    config = load_config()
    normalized = str(mode or get_search_mode(config)).strip().lower()
    if normalized not in {"frame", "chunk"}:
        normalized = get_search_mode(config)
    return normalized


def _clamp_top_k(top_k: Optional[int]) -> int:
    config = load_config()
    default_k = get_search_top_k(config)
    if top_k is None:
        return default_k
    try:
        value = int(top_k)
    except (TypeError, ValueError):
        return default_k
    return max(1, min(200, value))


def _count_library_videos() -> int:
    total = 0
    for library in list_libraries().values():
        files = library.get("files", {}) if isinstance(library, dict) else {}
        if isinstance(files, dict):
            total += len(files)
    return total


def _index_vector_count(search_index) -> int:
    return int(getattr(search_index, "ntotal", 0) or 0) if search_index is not None else 0


def _index_snapshot(mode: str) -> Dict[str, Any]:
    config = load_config()
    frame_index, _frame_ts, frame_paths = load_search_assets(config)
    chunk_index, _chunk_ranges, chunk_paths = load_chunk_search_assets(config)

    if mode == "chunk":
        search_index = chunk_index
        video_paths = chunk_paths
    else:
        search_index = frame_index
        video_paths = frame_paths

    vector_count = _index_vector_count(search_index)
    unique_paths = set()
    if video_paths:
        unique_paths = {str(path) for path in video_paths if path}
    index_ready = search_index is not None and vector_count > 0
    global_state = str(get_global_index_state() or "").strip().lower()
    frame_vector_count = _index_vector_count(frame_index)
    chunk_vector_count = _index_vector_count(chunk_index)
    return {
        "index_ready": index_ready,
        "vector_count": vector_count,
        "indexed_video_paths": len(unique_paths),
        "global_index_state": global_state or "fresh",
        "index_stale": global_state == "stale",
        "frame_index_ready": frame_index is not None and frame_vector_count > 0,
        "chunk_index_ready": chunk_index is not None and chunk_vector_count > 0,
        "frame_vector_count": frame_vector_count,
        "chunk_vector_count": chunk_vector_count,
    }


def _build_index_id(spec: Dict[str, Any], snapshot: Dict[str, Any]) -> str:
    model_id = str(spec.get("model_id") or spec.get("provider") or "unknown").strip()
    dimension = int(spec.get("dimension") or 0)
    metric = str(spec.get("metric") or "ip").strip().lower() or "ip"
    embedding_space = str(spec.get("embedding_space") or model_id).strip()
    state = str(snapshot.get("global_index_state") or "fresh").strip().lower()
    return f"{embedding_space}_{dimension}_{metric}_{state}"


def _build_capabilities(snapshot: Dict[str, Any]) -> Dict[str, bool]:
    ffmpeg_info = _build_ffmpeg_info()
    return {
        "text_search": True,
        "image_search": True,
        "frame_search": bool(snapshot.get("frame_index_ready")),
        "chunk_search": bool(snapshot.get("chunk_index_ready")),
        "export_manifest": False,
        "export_clip": False,
        "local_ffmpeg_clip": bool(ffmpeg_info.get("ffmpeg_available")),
    }


def _build_ffmpeg_info() -> Dict[str, Any]:
    from src.utils import has_ffmpeg, resolve_ffmpeg_path_info

    resolved_path, source = resolve_ffmpeg_path_info()
    available = bool(has_ffmpeg())
    path = str(resolved_path or "").strip()
    return {
        "ffmpeg_available": available,
        "ffmpeg_path": path,
        "ffmpeg_source": str(source or "missing"),
    }


def api_error_payload(code: str, message: str) -> Dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "ok": False,
        "error": {"code": str(code), "message": str(message)},
    }


def raise_api_error(status_code: int, code: str, message: str) -> None:
    if HTTPException is None:
        raise RuntimeError(f"{code}: {message}")
    raise HTTPException(status_code=status_code, detail=api_error_payload(code, message))


def build_health_payload(mode: Optional[str] = None) -> Dict[str, Any]:
    config = load_config()
    mode = _normalize_mode(mode)
    spec = get_active_embedding_spec(config=config)
    snapshot = _index_snapshot(mode)
    return {
        "api_version": API_VERSION,
        "ok": True,
        "service": "videoseek-agent-api",
        "index_ready": bool(snapshot["index_ready"]),
        "index_stale": bool(snapshot["index_stale"]),
        "global_index_state": snapshot["global_index_state"],
        "index_id": _build_index_id(spec, snapshot),
        "search_mode_default": get_search_mode(config),
        "search_mode_checked": mode,
        "model": spec.get("model_id") or spec.get("provider"),
        "provider": spec.get("provider"),
        "embedding_space": spec.get("embedding_space"),
        "dimension": int(spec.get("dimension") or 0),
        "metric": spec.get("metric"),
        "capabilities": _build_capabilities(snapshot),
        "ffmpeg": _build_ffmpeg_info(),
        "video_count": _count_library_videos(),
        "vector_count": snapshot["vector_count"],
        "indexed_video_paths": snapshot["indexed_video_paths"],
        "frame_vector_count": snapshot["frame_vector_count"],
        "chunk_vector_count": snapshot["chunk_vector_count"],
        "max_concurrent_searches": MAX_CONCURRENT_SEARCHES,
        "search_timeout_sec": SEARCH_TIMEOUT_SEC,
    }


def _filter_hits(hits: List[SearchHit], min_score: Optional[float]) -> List[SearchHit]:
    if min_score is None:
        return hits
    try:
        threshold = float(min_score)
    except (TypeError, ValueError):
        return hits
    return [hit for hit in hits if float(hit.score) >= threshold]


def _hits_to_payload(hits: List[SearchHit]) -> List[Dict[str, Any]]:
    payload = []
    for rank, hit in enumerate(hits, start=1):
        payload.append(
            {
                "rank": rank,
                "video_path": str(hit.video_path),
                "start_sec": float(hit.start_sec),
                "end_sec": float(hit.end_sec),
                "score": float(hit.score),
            }
        )
    return payload


def execute_agent_search(body: AgentSearchRequest) -> Dict[str, Any]:
    query_type = str(body.query_type or "text").strip().lower()
    if query_type not in {"text", "image_path"}:
        raise ValueError("query_type must be 'text' or 'image_path'")

    query = str(body.query or "").strip()
    if not query:
        raise ValueError("query is required")

    mode = _normalize_mode(body.mode)
    top_k = _clamp_top_k(body.top_k)
    snapshot = _index_snapshot(mode)
    if not snapshot["index_ready"]:
        raise IndexNotReadyError("Search index is not ready. Sync the library in VideoSeek first.")

    is_text = query_type == "text"
    if not is_text and not os.path.isfile(query):
        raise ValueError(f"image_path does not exist: {query}")

    with _search_semaphore:
        if mode == "chunk":
            hits = run_chunk_search(query, is_text=is_text, top_k=top_k)
        else:
            hits = run_search(query, is_text=is_text, top_k=top_k, search_mode="frame")

    hits = _filter_hits(hits, body.min_score)
    return {
        "api_version": API_VERSION,
        "ok": True,
        "query": query,
        "query_type": query_type,
        "mode": mode,
        "client_request_id": body.client_request_id,
        "hits": _hits_to_payload(hits),
        "meta": {
            "returned": len(hits),
            "top_k": top_k,
            "index_ready": True,
            "global_index_state": snapshot["global_index_state"],
        },
    }


class IndexNotReadyError(Exception):
    pass


class AgentApiService:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        if _IMPORT_ERROR is not None:
            raise RuntimeError("Missing FastAPI runtime. Install `fastapi` and `uvicorn`.") from _IMPORT_ERROR
        self.host = str(host)
        self.port = int(port)
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._started = threading.Event()
        self._lock = threading.Lock()

        self.app = FastAPI(title="VideoSeek Agent API", version=API_VERSION)
        self._register_exception_handlers()
        self.app.get("/api/v1/health")(self._health)
        self.app.post("/api/v1/search")(self._search)

    def _register_exception_handlers(self):
        from fastapi.exceptions import RequestValidationError

        @self.app.exception_handler(HTTPException)
        async def _handle_http_exception(_request, exc: HTTPException):
            body = exc.detail
            if isinstance(body, dict) and body.get("api_version") and body.get("error"):
                payload = body
            elif isinstance(body, dict) and "error" in body and isinstance(body["error"], dict):
                payload = body
            elif isinstance(body, dict):
                payload = api_error_payload(
                    str(body.get("code") or body.get("error") or "request_failed"),
                    str(body.get("message") or body),
                )
            else:
                payload = api_error_payload("request_failed", str(body))
            return JSONResponse(status_code=exc.status_code, content=payload)

        @self.app.exception_handler(RequestValidationError)
        async def _handle_validation_error(_request, exc: RequestValidationError):
            return JSONResponse(
                status_code=400,
                content=api_error_payload("invalid_request", str(exc.errors())),
            )

    def start(self):
        with self._lock:
            if self.is_running():
                return
            config = uvicorn.Config(
                self.app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
            )
            self._server = uvicorn.Server(config)
            self._thread = threading.Thread(target=self._run_server, name="AgentApiServer", daemon=True)
            self._thread.start()

        started = False
        for _ in range(30):
            if self._server is not None and getattr(self._server, "started", False):
                started = True
                break
            if self._thread is None or not self._thread.is_alive():
                break
            time.sleep(0.1)
        if not started:
            raise RuntimeError("Agent API server failed to start within 3 seconds.")
        self._started.set()
        logger.info("Agent API listening on http://%s:%s", self.host, self.port)

    def stop(self):
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self._started.clear()

        if server is None:
            return

        server.should_exit = True
        if thread is not None:
            thread.join(timeout=3.0)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._started.is_set()

    def get_base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _run_server(self):
        try:
            self._server.run()
        except Exception:
            logger.exception("Agent API server crashed.")
        finally:
            self._started.clear()

    async def _health(self, mode: Optional[str] = None):
        return build_health_payload(mode=mode)

    async def _search(self, body: AgentSearchRequest):
        started = time.perf_counter()
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(execute_agent_search, body),
                timeout=SEARCH_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            raise_api_error(
                503,
                "engine_busy",
                f"Search timed out after {int(SEARCH_TIMEOUT_SEC)} seconds.",
            )
        except IndexNotReadyError as exc:
            raise_api_error(409, "index_not_ready", str(exc))
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except RuntimeError as exc:
            logger.exception("Agent search failed.")
            raise_api_error(422, "query_failed", str(exc))
        except Exception as exc:
            logger.exception("Agent search failed.")
            raise_api_error(422, "query_failed", str(exc))

        payload.setdefault("meta", {})
        payload["meta"]["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return JSONResponse(payload)


def is_agent_api_enabled(config=None) -> bool:
    """Whether the localhost Agent API should run (config + env override)."""
    forced = str(os.environ.get("VIDEOSEEK_AGENT_API", "")).strip().lower()
    if forced in {"0", "false", "no", "off"}:
        return False
    if forced in {"1", "true", "yes", "on"}:
        return True
    if config is None:
        config = load_config()
    return bool(config.get("agent_api_enabled", False))


def agent_api_enabled() -> bool:
    return is_agent_api_enabled()
