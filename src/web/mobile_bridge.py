import os
import secrets
import socket
import threading
import time
import uuid
from typing import Callable, Optional

try:
    from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
    from fastapi.responses import HTMLResponse, JSONResponse
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
from src.utils import ensure_folder_exists, get_app_data_dir, get_resource_path

logger = get_logger("mobile_bridge")


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class MobileBridgeService:
    def __init__(
        self,
        on_image_received: Callable[[str, str], None],
        host: str = "0.0.0.0",
        port: int = 8918,
    ):
        if _IMPORT_ERROR is not None:
            raise RuntimeError("Missing FastAPI runtime. Install `fastapi` and `uvicorn`.") from _IMPORT_ERROR
        self.host = str(host)
        self.port = int(port)
        self.token = secrets.token_urlsafe(18)
        self.upload_dir = os.path.join(get_app_data_dir(), "mobile_uploads")
        self._on_image_received = on_image_received
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._started = threading.Event()
        self._lock = threading.Lock()

        self.app = FastAPI(title="VideoSeek Mobile Bridge")
        static_dir = get_resource_path("static")
        self.app.mount("/static", StaticFiles(directory=static_dir), name="static")
        self.app.get("/", response_class=HTMLResponse)(self._index)
        self.app.post("/search")(self._search)
        self.app.get("/health")(self._health)

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

    async def _index(self, request: Request):
        token = str(request.query_params.get("token", "") or "").strip()
        if token != self.token:
            raise HTTPException(status_code=403, detail="Invalid access token.")

        template_path = get_resource_path(os.path.join("static", "index.html"))
        with open(template_path, "r", encoding="utf-8") as handle:
            html = handle.read()
        return html.replace("__UPLOAD_TOKEN__", self.token)

    async def _search(
        self,
        request: Request,
        token: str = Form(""),
        file: UploadFile = File(...),
    ):
        if str(token).strip() != self.token:
            raise HTTPException(status_code=403, detail="Invalid upload token.")
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

        client_host = request.client.host if request.client else ""
        try:
            self._on_image_received(target_path, client_host)
        except Exception as exc:
            logger.exception("Failed to hand off uploaded image to UI.")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        logger.info("Accepted mobile upload: %s", target_path)
        return JSONResponse({"ok": True, "message": "图片已发送到电脑端，正在触发搜索。"})

    async def _health(self):
        return {"ok": True, "running": self.is_running()}
