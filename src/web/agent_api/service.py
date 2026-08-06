"""AgentApiService: FastAPI routes and server lifecycle."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional

from src.app.logging_utils import get_logger
from src.services.agent_clip_service import execute_agent_batch_export_clips, execute_agent_export_clip
from src.services.agent_library_service import (
    list_agent_libraries,
    list_agent_subtitle_libraries,
    list_agent_subtitle_videos,
    list_agent_videos,
)
from src.services.agent_starter_service import build_agent_doc_payload, build_agent_starter_payload

from ._fastapi import FastAPI, HTTPException, JSONResponse, PlainTextResponse, _IMPORT_ERROR, uvicorn
from .constants import API_VERSION, DEFAULT_HOST, DEFAULT_PORT
from .errors import IndexNotReadyError, SearchEngineBusyError, api_error_payload, raise_api_error
from .export_ops import _resolve_batch_search_export_timeout_sec, execute_export_manifest
from .health import build_health_payload
from .schemas import (
    AgentBatchExportClipsRequest,
    AgentBatchSearchRequest,
    AgentExportClipRequest,
    AgentManifestRequest,
    AgentSearchRequest,
)
from .search import (
    _resolve_search_timeout_sec,
    execute_agent_batch_search,
    execute_agent_search,
    get_agent_search_preset,
    get_agent_search_telemetry,
    list_agent_search_presets,
)

logger = get_logger("agent_api")


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
        self.app.get("/api/v1/agent-starter")(self._agent_starter)
        self.app.get("/api/v1/agent-doc")(self._agent_doc)
        self.app.get("/api/v1/libraries")(self._libraries)
        self.app.get("/api/v1/libraries/videos")(self._library_videos)
        self.app.get("/api/v1/videos")(self._videos)
        self.app.get("/api/v1/subtitle-libraries")(self._subtitle_libraries)
        self.app.get("/api/v1/subtitle-libraries/videos")(self._subtitle_library_videos)
        self.app.get("/api/v1/search/presets")(self._search_presets)
        self.app.get("/api/v1/search/presets/{preset_id}")(self._search_preset_detail)
        self.app.post("/api/v1/search")(self._search)
        self.app.post("/api/v1/search/batch")(self._search_batch)
        self.app.get("/api/v1/search/telemetry")(self._search_telemetry)
        self.app.post("/api/v1/export/manifest")(self._export_manifest)
        self.app.post("/api/v1/export/clip")(self._export_clip)
        self.app.post("/api/v1/export/clips/batch")(self._export_clips_batch)

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
        from .constants import configure_search_concurrency

        configure_search_concurrency()
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

    async def _agent_starter(self, mode: Optional[str] = None, locale: Optional[str] = None):
        health = build_health_payload(mode=mode)
        base_url = f"http://{self.host}:{self.port}"
        return build_agent_starter_payload(base_url, health, locale=locale or "zh")

    async def _agent_doc(self, format: Optional[str] = None):
        fmt = str(format or "json").strip().lower()
        if fmt not in {"json", "text"}:
            raise_api_error(400, "invalid_request", "format must be json or text")
        try:
            payload = await asyncio.to_thread(build_agent_doc_payload, api_version=API_VERSION)
        except FileNotFoundError as exc:
            raise_api_error(404, "doc_not_found", str(exc))
        except OSError as exc:
            logger.exception("Agent doc read failed.")
            raise_api_error(500, "query_failed", str(exc))
        if fmt == "text":
            return PlainTextResponse(
                payload["content"],
                media_type="text/markdown; charset=utf-8",
                headers={"X-VideoSeek-Doc-Path": str(payload.get("full_doc_path") or "")},
            )
        return payload

    async def _search_presets(self):
        try:
            return await asyncio.to_thread(list_agent_search_presets)
        except Exception as exc:
            logger.exception("Agent preset list failed.")
            raise_api_error(500, "query_failed", str(exc))

    async def _libraries(self):
        try:
            return await asyncio.to_thread(list_agent_libraries)
        except Exception as exc:
            logger.exception("Agent library list failed.")
            raise_api_error(500, "query_failed", str(exc))

    async def _subtitle_libraries(self):
        try:
            return await asyncio.to_thread(list_agent_subtitle_libraries)
        except Exception as exc:
            logger.exception("Agent subtitle library list failed.")
            raise_api_error(500, "query_failed", str(exc))

    async def _subtitle_library_videos(
        self,
        library_path: Optional[str] = None,
        video_id: Optional[str] = None,
        q: Optional[str] = None,
        ready_only: bool = True,
        limit: int = 500,
        offset: int = 0,
    ):
        try:
            return await asyncio.to_thread(
                list_agent_subtitle_videos,
                library_path,
                video_id=video_id,
                q=q,
                ready_only=ready_only,
                limit=limit,
                offset=offset,
            )
        except KeyError as exc:
            raise_api_error(404, "invalid_request", str(exc))
        except Exception as exc:
            logger.exception("Agent subtitle video list failed.")
            raise_api_error(500, "query_failed", str(exc))

    async def _library_videos(
        self,
        library_path: Optional[str] = None,
        video_id: Optional[str] = None,
        q: Optional[str] = None,
        ready_only: bool = True,
        limit: int = 500,
        offset: int = 0,
    ):
        return await self._videos(
            library_path=library_path,
            video_id=video_id,
            q=q,
            ready_only=ready_only,
            limit=limit,
            offset=offset,
        )

    async def _videos(
        self,
        library_path: Optional[str] = None,
        video_id: Optional[str] = None,
        q: Optional[str] = None,
        ready_only: bool = True,
        limit: int = 500,
        offset: int = 0,
    ):
        try:
            payload = await asyncio.to_thread(
                list_agent_videos,
                library_path,
                video_id=video_id,
                q=q,
                ready_only=ready_only,
                limit=limit,
                offset=offset,
            )
        except KeyError as exc:
            raise_api_error(404, "invalid_request", str(exc))
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except Exception as exc:
            logger.exception("Agent synced videos list failed.")
            raise_api_error(500, "query_failed", str(exc))
        return JSONResponse(payload)

    async def _search_preset_detail(self, preset_id: str):
        try:
            return await asyncio.to_thread(get_agent_search_preset, preset_id)
        except KeyError as exc:
            raise_api_error(404, "invalid_request", str(exc))
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except Exception as exc:
            logger.exception("Agent preset detail failed.")
            raise_api_error(500, "query_failed", str(exc))

    async def _search_telemetry(self, locale: Optional[str] = None):
        try:
            return await asyncio.to_thread(get_agent_search_telemetry, locale=locale or "zh")
        except Exception as exc:
            logger.exception("Agent search telemetry failed.")
            raise_api_error(500, "query_failed", str(exc))

    async def _search(self, body: AgentSearchRequest):
        started = time.perf_counter()
        timeout_sec = _resolve_search_timeout_sec(body)
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(execute_agent_search, body),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            raise_api_error(
                503,
                "engine_busy",
                (
                    f"Search timed out after {int(timeout_sec)} seconds. "
                    "For precise image search, allow more time or reduce top_k / pixel rerank settings."
                ),
            )
        except SearchEngineBusyError as exc:
            raise_api_error(503, "engine_busy", str(exc))
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
        payload["meta"]["search_timeout_sec"] = int(timeout_sec)
        return JSONResponse(payload)

    async def _search_batch(self, body: AgentBatchSearchRequest):
        started = time.perf_counter()
        timeout_sec = _resolve_batch_search_export_timeout_sec(body)
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(execute_agent_batch_search, body),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            detail = (
                f"Batch search/export timed out after {int(timeout_sec)} seconds. "
                "Reduce batch size, use search_precision_mode=fast, or raise agent_api_batch_timeout_sec."
            )
            raise_api_error(503, "engine_busy", detail)
        except SearchEngineBusyError as exc:
            raise_api_error(503, "engine_busy", str(exc))
        except IndexNotReadyError as exc:
            raise_api_error(409, "index_not_ready", str(exc))
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except RuntimeError as exc:
            message = str(exc)
            if "ffmpeg" in message.lower() and "not available" in message.lower():
                raise_api_error(503, "engine_busy", message)
            raise_api_error(422, "export_failed", message)
        except Exception as exc:
            logger.exception("Agent batch search failed.")
            raise_api_error(422, "query_failed", str(exc))

        payload.setdefault("meta", {})
        payload["meta"]["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        payload["meta"]["batch_timeout_sec"] = int(timeout_sec)
        if body.export is not None:
            payload["meta"]["batch_export_enabled"] = True
        return JSONResponse(payload)

    async def _export_manifest(self, body: AgentManifestRequest):
        started = time.perf_counter()
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(execute_export_manifest, body),
                timeout=30.0,
            )
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except Exception as exc:
            logger.exception("Agent manifest export failed.")
            raise_api_error(422, "query_failed", str(exc))

        payload.setdefault("meta", {})
        payload["meta"]["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return JSONResponse(payload)

    async def _export_clip(self, body: AgentExportClipRequest):
        started = time.perf_counter()
        try:
            from .export_ops import resolve_export_clip_output_path

            output_path = resolve_export_clip_output_path(
                output_path=body.output_path,
                output_dir=body.output_dir,
                video_path=body.video_path,
                start_sec=body.start_sec,
                end_sec=body.end_sec,
                client_request_id=body.client_request_id,
            )
            payload = await asyncio.wait_for(
                asyncio.to_thread(
                    execute_agent_export_clip,
                    video_path=body.video_path,
                    start_sec=body.start_sec,
                    end_sec=body.end_sec,
                    output_path=output_path,
                    client_request_id=body.client_request_id,
                    silent=body.silent,
                    encode_mode=body.encode_mode,
                ),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            raise_api_error(503, "engine_busy", "Clip export timed out after 120 seconds.")
        except FileNotFoundError as exc:
            raise_api_error(404, "invalid_request", str(exc))
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except RuntimeError as exc:
            message = str(exc)
            if "queue is busy" in message.lower():
                raise_api_error(503, "engine_busy", message)
            logger.exception("Agent clip export failed.")
            raise_api_error(422, "export_failed", message)
        except Exception as exc:
            logger.exception("Agent clip export failed.")
            raise_api_error(422, "export_failed", str(exc))

        payload.setdefault("meta", {})
        payload["meta"]["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return JSONResponse(payload)

    async def _export_clips_batch(self, body: AgentBatchExportClipsRequest):
        from src.services.agent_clip_service import _resolve_batch_export_timeout_sec
        from src.utils import normalize_export_encode_mode

        started = time.perf_counter()
        default_mode = normalize_export_encode_mode(body.encode_mode or "copy")
        timeout_sec = _resolve_batch_export_timeout_sec(len(body.items or []), default_mode)
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(execute_agent_batch_export_clips, body),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            raise_api_error(
                503,
                "engine_busy",
                (
                    f"Batch clip export timed out after {int(timeout_sec)} seconds. "
                    "Reduce batch size or use encode_mode=copy."
                ),
            )
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except RuntimeError as exc:
            message = str(exc)
            if "ffmpeg" in message.lower() and "not available" in message.lower():
                raise_api_error(503, "engine_busy", message)
            raise_api_error(422, "export_failed", message)
        except Exception as exc:
            logger.exception("Agent batch clip export failed.")
            raise_api_error(422, "export_failed", str(exc))

        payload.setdefault("meta", {})
        payload["meta"]["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        payload["meta"]["batch_timeout_sec"] = int(timeout_sec)
        return JSONResponse(payload)
