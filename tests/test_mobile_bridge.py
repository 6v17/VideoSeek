import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.modules.setdefault("numpy", types.SimpleNamespace())

if "fastapi" not in sys.modules:
    fastapi_module = types.ModuleType("fastapi")
    responses_module = types.ModuleType("fastapi.responses")
    staticfiles_module = types.ModuleType("fastapi.staticfiles")

    class _FastAPI:
        def __init__(self, *args, **kwargs):
            self.mounted = []

        def mount(self, *args, **kwargs):
            self.mounted.append((args, kwargs))

        def get(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

        def post(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

    class _HTTPException(Exception):
        def __init__(self, status_code=400, detail=""):
            self.status_code = status_code
            self.detail = detail
            super().__init__(f"{status_code}: {detail}")

    class _StaticFiles:
        def __init__(self, directory=None, **_kwargs):
            self.directory = directory

    def _form(value=""):
        return value

    def _file(value=None):
        return value

    fastapi_module.FastAPI = _FastAPI
    fastapi_module.File = _file
    fastapi_module.Form = _form
    fastapi_module.HTTPException = _HTTPException
    fastapi_module.Request = object
    fastapi_module.UploadFile = object
    responses_module.HTMLResponse = str
    responses_module.JSONResponse = dict
    responses_module.Response = lambda content="", media_type="": (content, media_type)
    staticfiles_module.StaticFiles = _StaticFiles

    sys.modules["fastapi"] = fastapi_module
    sys.modules["fastapi.responses"] = responses_module
    sys.modules["fastapi.staticfiles"] = staticfiles_module

if "uvicorn" not in sys.modules:
    uvicorn_module = types.ModuleType("uvicorn")

    class _Config:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _Server:
        def __init__(self, config):
            self.config = config
            self.started = False
            self.should_exit = False

        def run(self):
            self.started = True

    uvicorn_module.Config = _Config
    uvicorn_module.Server = _Server
    sys.modules["uvicorn"] = uvicorn_module

from src.web import mobile_bridge
from src.web.mobile_bridge import MobileBridgeService, cleanup_stale_mobile_uploads, read_mobile_upload_js


class MobileBridgeServiceTests(unittest.TestCase):
    def setUp(self):
        mobile_bridge._MOBILE_UPLOAD_JS_CACHE = None

    @patch("src.web.mobile_bridge.os.path.isfile", return_value=False)
    @patch("src.web.mobile_bridge.os.path.isdir", return_value=False)
    @patch("src.web.mobile_bridge.get_resource_path")
    @patch(
        "src.web.mobile_bridge.get_data_storage_paths",
        return_value={"mobile_upload_dir": "D:/Migrated/data/mobile_uploads"},
    )
    @patch("src.web.mobile_bridge.get_app_data_dir", return_value="D:/VideoSeek")
    def test_missing_static_resources_fall_back_to_embedded_page(
        self,
        _mock_app_data_dir,
        _mock_storage_paths,
        mock_get_resource_path,
        _mock_isdir,
        _mock_isfile,
    ):
        mock_get_resource_path.side_effect = lambda relative: f"D:/bundle/{relative}"

        service = MobileBridgeService(on_search_requested=lambda *_args: None)

        self.assertEqual(service.upload_dir, "D:/Migrated/data/mobile_uploads")
        html = service._load_index_html()

        self.assertIn("__UPLOAD_TOKEN__", html)
        self.assertIn("Upload an image", html)
        self.assertIn("/static/mobile_upload.js", html)

    def test_read_mobile_upload_js_loads_bundled_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            js_path = Path(tmp) / "static" / "mobile_upload.js"
            js_path.parent.mkdir(parents=True)
            js_path.write_text("function submitImage() {}", encoding="utf-8")
            with patch("src.web.mobile_bridge.get_resource_path", return_value=str(js_path)):
                payload = read_mobile_upload_js()
            self.assertIn("submitImage", payload)

    def test_cleanup_stale_mobile_uploads_keeps_recent_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(3):
                path = root / f"upload_{index}.jpg"
                path.write_bytes(b"x")
                if index < 2:
                    stale = path.stat().st_mtime - (8 * 24 * 3600)
                    import os

                    os.utime(path, (stale, stale))

            removed = cleanup_stale_mobile_uploads(str(root), max_age_sec=7 * 24 * 3600, keep_recent=1)

            remaining = sorted(root.iterdir())
            self.assertEqual(removed, 2)
            self.assertEqual(len(remaining), 1)
            self.assertTrue(remaining[0].name.startswith("upload_"))

    def test_resolve_mobile_bridge_host_prefers_lan_over_all_interfaces(self):
        from src.web.mobile_bridge import resolve_mobile_bridge_host

        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("VIDEOSEEK_MOBILE_BRIDGE_HOST", None)
            with patch("src.services.team_paths.detect_lan_ip", return_value="192.168.1.20"):
                self.assertEqual(resolve_mobile_bridge_host("0.0.0.0"), "192.168.1.20")
                self.assertEqual(resolve_mobile_bridge_host(None), "192.168.1.20")

        with patch.dict("os.environ", {"VIDEOSEEK_MOBILE_BRIDGE_HOST": "0.0.0.0"}):
            self.assertEqual(resolve_mobile_bridge_host(None), "0.0.0.0")

    def test_read_upload_limited_rejects_oversized_payload(self):
        import asyncio

        from src.web.mobile_bridge import MAX_MOBILE_UPLOAD_BYTES, MobileBridgeService

        class _FakeUpload:
            filename = "big.jpg"
            content_type = "image/jpeg"

            def __init__(self, chunks):
                self._chunks = list(chunks)

            async def read(self, size=-1):
                if not self._chunks:
                    return b""
                return self._chunks.pop(0)

        with patch(
            "src.web.mobile_bridge.get_data_storage_paths",
            return_value={"mobile_upload_dir": "D:/tmp/uploads"},
        ), patch("src.web.mobile_bridge.get_app_data_dir", return_value="D:/VideoSeek"), patch(
            "src.web.mobile_bridge.os.path.isdir", return_value=False
        ), patch(
            "src.web.mobile_bridge.get_resource_path",
            side_effect=lambda relative: f"D:/bundle/{relative}",
        ):
            service = MobileBridgeService(on_search_requested=lambda *_a: None)

        oversized = [
            b"x" * (1024 * 1024),
            b"y" * (MAX_MOBILE_UPLOAD_BYTES),
        ]
        with self.assertRaises(Exception) as ctx:
            asyncio.run(service._read_upload_limited(_FakeUpload(oversized)))
        exc = ctx.exception
        status = getattr(exc, "status_code", None)
        detail = str(getattr(exc, "detail", "") or exc)
        self.assertTrue(status == 413 or "limit" in detail.lower() or "exceed" in detail.lower())


if __name__ == "__main__":
    unittest.main()
