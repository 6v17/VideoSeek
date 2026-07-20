import os
import secrets
import socket
import threading
import time
import uuid
from typing import Callable, Optional

_MOBILE_UPLOAD_JS_CACHE: str | None = None

try:
    from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
    from fastapi.responses import HTMLResponse, JSONResponse, Response
    from fastapi.staticfiles import StaticFiles
    import uvicorn
except ImportError as exc:
    FastAPI = None
    File = Form = HTTPException = Request = UploadFile = None
    HTMLResponse = JSONResponse = None
    StaticFiles = None
    uvicorn = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from src.app.logging_utils import get_logger
from src.app.config import get_data_storage_paths
from src.services.mobile_search_service import (
    build_mobile_search_payload,
    get_mobile_search_defaults,
    normalize_mobile_search_kind,
    parse_mobile_fusion,
)
from src.utils import ensure_folder_exists, get_app_data_dir, get_resource_path

logger = get_logger("mobile_bridge")

_FALLBACK_UPLOAD_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>VideoSeek Mobile Upload</title>
    <style>
        body {
            margin: 0;
            min-height: 100vh;
            font-family: "Segoe UI", sans-serif;
            background: linear-gradient(145deg, #dbeafe 0%, #eff6ff 48%, #f8fafc 100%);
            color: #0f172a;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px 16px;
        }
        .card {
            width: min(100%, 420px);
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid rgba(148, 163, 184, 0.28);
            border-radius: 24px;
            box-shadow: 0 30px 80px rgba(15, 23, 42, 0.12);
            padding: 24px 20px;
        }
        h1 { margin: 0 0 10px; font-size: 28px; line-height: 1.1; }
        p { margin: 0; color: #475569; line-height: 1.5; }
        .picker {
            margin-top: 24px;
            padding: 28px 14px;
            border: 2px dashed #bfdbfe;
            border-radius: 20px;
            background: #fff;
            text-align: center;
        }
        #preview {
            display: none;
            max-width: 100%;
            max-height: 260px;
            border-radius: 16px;
            margin: 0 auto;
        }
        #file-input { display: none; }
        .actions { display: flex; gap: 10px; margin-top: 18px; }
        button {
            border: none;
            border-radius: 14px;
            padding: 14px 16px;
            font-size: 15px;
            font-weight: 700;
            cursor: pointer;
        }
        .primary {
            flex: 1;
            background: #2563eb;
            color: #fff;
        }
        .secondary {
            background: transparent;
            color: #64748b;
            border: 1px solid rgba(148, 163, 184, 0.38);
        }
        .status {
            margin-top: 14px;
            min-height: 22px;
            color: #475569;
            font-size: 13px;
            line-height: 1.5;
        }
    </style>
</head>
<body>
<div class="card">
    <h1>Upload an image</h1>
    <p>Send a photo to this desktop. Results stay in the VideoSeek window on the computer.</p>

    <div class="picker" onclick="document.getElementById('file-input').click()">
        <div id="placeholder">
            <div style="font-size: 40px;">&#128247;</div>
            <strong>Select one image</strong>
            <div style="margin-top: 6px; color: #64748b; font-size: 13px;">JPG / PNG / HEIC (iPhone)</div>
        </div>
        <img id="preview" alt="preview">
    </div>

    <input id="file-input" type="file" accept="image/*" onchange="previewImage()">

    <div class="actions">
        <button class="primary" id="submit-btn" onclick="submitImage()">Send to desktop</button>
        <button class="secondary" onclick="clearFile()">Reset</button>
    </div>
    <div class="status" id="status"></div>
</div>

<script>
const uploadToken = "__UPLOAD_TOKEN__";
</script>
<script src="/static/mobile_upload.js"></script>
</body>
</html>
"""


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def read_mobile_upload_js() -> str:
    global _MOBILE_UPLOAD_JS_CACHE
    if _MOBILE_UPLOAD_JS_CACHE is not None:
        return _MOBILE_UPLOAD_JS_CACHE
    js_path = get_resource_path(os.path.join("static", "mobile_upload.js"))
    try:
        with open(js_path, "r", encoding="utf-8") as handle:
            _MOBILE_UPLOAD_JS_CACHE = handle.read()
    except OSError:
        logger.warning("Mobile upload JS missing at %s", js_path)
        _MOBILE_UPLOAD_JS_CACHE = ""
    return _MOBILE_UPLOAD_JS_CACHE


def cleanup_stale_mobile_uploads(
    upload_dir: str,
    *,
    max_age_sec: int = 7 * 24 * 3600,
    keep_recent: int = 20,
) -> int:
    """Delete old mobile query images; always keep the newest `keep_recent` files."""
    if not upload_dir or not os.path.isdir(upload_dir):
        return 0
    entries: list[tuple[float, str]] = []
    for name in os.listdir(upload_dir):
        path = os.path.join(upload_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            entries.append((os.path.getmtime(path), path))
        except OSError:
            continue
    if not entries:
        return 0

    entries.sort(key=lambda item: item[0], reverse=True)
    cutoff = time.time() - max(0, int(max_age_sec))
    removed = 0
    for index, (mtime, path) in enumerate(entries):
        if index < max(0, int(keep_recent)):
            continue
        if mtime >= cutoff:
            continue
        try:
            os.remove(path)
            removed += 1
        except OSError as exc:
            logger.warning("Failed to remove stale mobile upload %s: %s", path, exc)
    return removed


class MobileBridgeService:
    def __init__(
        self,
        on_search_requested: Callable[[dict], None],
        host: str = "0.0.0.0",
        port: int = 8918,
    ):
        if _IMPORT_ERROR is not None:
            raise RuntimeError("Missing FastAPI runtime. Install `fastapi` and `uvicorn`.") from _IMPORT_ERROR
        self.host = str(host)
        self.port = int(port)
        self.token = secrets.token_urlsafe(18)
        self.upload_dir = str(get_data_storage_paths().get("mobile_upload_dir", "") or "")
        if not self.upload_dir:
            self.upload_dir = os.path.join(get_app_data_dir(), "mobile_uploads")
        self._on_search_requested = on_search_requested
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._started = threading.Event()
        self._lock = threading.Lock()
        self._static_dir = get_resource_path("static")
        self._template_path = get_resource_path(os.path.join("static", "index.html"))

        self.app = FastAPI(title="VideoSeek Mobile Bridge")
        self.app.get("/static/mobile_upload.js")(self._mobile_upload_js)
        if os.path.isdir(self._static_dir):
            self.app.mount("/static", StaticFiles(directory=self._static_dir), name="static")
        else:
            logger.warning("Mobile bridge static directory missing: %s", self._static_dir)
        self.app.get("/", response_class=HTMLResponse)(self._index)
        self.app.get("/config")(self._config)
        self.app.post("/preview")(self._preview)
        self.app.post("/search")(self._search)
        self.app.get("/health")(self._health)

    def start(self):
        with self._lock:
            if self.is_running():
                return
            ensure_folder_exists(self.upload_dir)
            removed = cleanup_stale_mobile_uploads(self.upload_dir)
            if removed:
                logger.info("Removed %s stale mobile upload file(s).", removed)
            config = uvicorn.Config(
                self.app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
            )
            self._server = uvicorn.Server(config)
            self._thread = threading.Thread(target=self._run_server, name="MobileBridgeServer", daemon=True)
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
            raise RuntimeError("Mobile bridge server failed to start within 3 seconds.")
        self._started.set()

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

    def is_running(self):
        return self._thread is not None and self._thread.is_alive() and self._started.is_set()

    def get_access_url(self):
        return f"http://{get_local_ip()}:{self.port}/?token={self.token}"

    def _run_server(self):
        try:
            self._server.run()
        except Exception:
            logger.exception("Mobile bridge server crashed.")
        finally:
            self._started.clear()

    def _validate_access_token(self, token: str) -> None:
        if str(token or "").strip() != self.token:
            raise HTTPException(status_code=403, detail="Invalid access token.")

    async def _index(self, request: Request):
        self._validate_access_token(str(request.query_params.get("token", "") or ""))

        html = self._load_index_html()
        return html.replace("__UPLOAD_TOKEN__", self.token)

    async def _config(self, request: Request):
        self._validate_access_token(str(request.query_params.get("token", "") or ""))
        return JSONResponse(get_mobile_search_defaults())

    async def _mobile_upload_js(self):
        payload = read_mobile_upload_js()
        if not payload:
            raise HTTPException(status_code=404, detail="Mobile upload script unavailable.")
        return Response(content=payload, media_type="application/javascript")

    def _load_index_html(self):
        if os.path.isfile(self._template_path):
            with open(self._template_path, "r", encoding="utf-8") as handle:
                return handle.read()

        logger.warning("Mobile bridge page missing, using embedded fallback: %s", self._template_path)
        return _FALLBACK_UPLOAD_PAGE

    async def _save_upload_file(self, file: UploadFile) -> str:
        if file is None or not file.filename:
            raise HTTPException(status_code=400, detail="No image file received.")
        content_type = str(file.content_type or "").lower()
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Only image uploads are supported.")
        suffix = os.path.splitext(file.filename)[1] or ".jpg"
        filename = f"{int(time.time() * 1000)}_{uuid.uuid4().hex}{suffix}"
        target_path = os.path.join(self.upload_dir, filename)
        ensure_folder_exists(target_path)
        payload = await file.read()
        with open(target_path, "wb") as handle:
            handle.write(payload)
        return target_path

    async def _preview(
        self,
        token: str = Form(""),
        file: UploadFile = File(...),
    ):
        if str(token).strip() != self.token:
            raise HTTPException(status_code=403, detail="Invalid upload token.")
        target_path = await self._save_upload_file(file)
        try:
            from src.core.image_io import encode_preview_jpeg

            jpeg_bytes = encode_preview_jpeg(target_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            try:
                os.remove(target_path)
            except OSError:
                pass
        return Response(content=jpeg_bytes, media_type="image/jpeg")

    async def _search(
        self,
        request: Request,
        token: str = Form(""),
        search_kind: str = Form("image"),
        query: str = Form(""),
        text_weight: str = Form(""),
        image_search_mode: str = Form(""),
        search_mode: str = Form(""),
        dialogue_search_mode: str = Form(""),
        file: UploadFile = File(None),
        files: list[UploadFile] = File(None),
    ):
        self._validate_access_token(token)
        kind = normalize_mobile_search_kind(search_kind)
        cleaned_query = str(query or "").strip()
        saved_paths: list[str] = []

        uploads: list[UploadFile] = []
        if files:
            uploads.extend(files)
        if file is not None and str(getattr(file, "filename", "") or "").strip():
            uploads.append(file)

        for upload in uploads:
            if upload is None or not str(getattr(upload, "filename", "") or "").strip():
                continue
            target_path = await self._save_upload_file(upload)
            from src.core.image_io import normalize_image_upload

            try:
                target_path = normalize_image_upload(target_path)
            except ValueError as exc:
                for path in saved_paths:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                try:
                    os.remove(target_path)
                except OSError:
                    pass
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            saved_paths.append(target_path)

        fusion = parse_mobile_fusion(
            text_weight,
            has_text=bool(cleaned_query),
            has_image=bool(saved_paths),
        )
        try:
            payload = build_mobile_search_payload(
                search_kind=kind,
                query=cleaned_query,
                image_paths=saved_paths,
                fusion=fusion,
                source=request.client.host if request.client else "",
                image_search_mode=image_search_mode,
                search_mode=search_mode,
                dialogue_search_mode=dialogue_search_mode,
            )
        except ValueError as exc:
            for path in saved_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            self._on_search_requested(payload)
        except Exception as exc:
            logger.exception("Failed to hand off mobile search request to UI.")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        logger.info("Accepted mobile search request: kind=%s", kind)
        labels = {
            "image": "图搜",
            "text": "文搜",
            "compose": "组合搜索",
            "dialogue": "字幕搜索",
        }
        return JSONResponse(
            {
                "ok": True,
                "message": f"已提交{labels.get(kind, '搜索')}请求，请在电脑端查看结果。",
                "search_kind": kind,
            }
        )

    async def _health(self):
        return {"ok": True, "running": self.is_running()}
