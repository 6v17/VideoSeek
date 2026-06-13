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
        pass

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


if __name__ == "__main__":
    unittest.main()
