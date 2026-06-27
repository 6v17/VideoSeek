import os
import sys
import types
import unittest
from unittest.mock import patch

try:
    import cv2 as _real_cv2
    sys.modules["cv2"] = _real_cv2
except ImportError:
    sys.modules.setdefault("cv2", types.SimpleNamespace())
try:
    import numpy as _real_numpy
    sys.modules["numpy"] = _real_numpy
except ImportError:
    sys.modules.setdefault("numpy", types.SimpleNamespace())
try:
    import onnxruntime as _real_ort
    sys.modules["onnxruntime"] = _real_ort
except ImportError:
    sys.modules.setdefault("onnxruntime", types.SimpleNamespace())
try:
    import faiss as _real_faiss
    sys.modules["faiss"] = _real_faiss
except ImportError:
    sys.modules.setdefault("faiss", types.SimpleNamespace())
try:
    import ftfy as _real_ftfy
    sys.modules["ftfy"] = _real_ftfy
except ImportError:
    sys.modules.setdefault("ftfy", types.SimpleNamespace(fix_text=lambda text: text))
sys.modules.setdefault("regex", __import__("re"))

from src.core import clip_embedding
from src.services import about_service, notice_service, version_service
from src import utils


class NoticeServiceTests(unittest.TestCase):
    def test_normalize_notice_supports_list_body_and_meta(self):
        texts = {"notice_heading": "Heading", "notice_subtitle": "Subtitle", "notice_body": "Body"}

        result = notice_service._normalize_notice(
            {
                "title": "Update",
                "subtitle": "Notes",
                "body": ["one", "two"],
                "format": "html",
                "version": "1.0.2",
                "date": "2026-04-01",
            },
            texts,
        )

        self.assertEqual(result["title"], "Update")
        self.assertEqual(result["format"], "html")
        self.assertIn("1. one", result["body"])
        self.assertIn("1.0.2 | 2026-04-01", result["subtitle"])

    def test_normalize_notice_falls_back_to_plain_for_unknown_format(self):
        texts = {"notice_heading": "Heading", "notice_subtitle": "Subtitle", "notice_body": "Body"}

        result = notice_service._normalize_notice({"format": "markdown"}, texts)

        self.assertEqual(result["format"], "plain")


class AboutServiceTests(unittest.TestCase):
    def test_normalize_about_supports_html_and_list_body(self):
        texts = {"about_badge": "Badge", "app_name": "VideoSeek", "about_body": "Body"}

        result = about_service._normalize_about(
            {
                "badge": "Remote Badge",
                "title": "Remote Title",
                "body": ["line one", "line two"],
                "format": "html",
            },
            texts,
        )

        self.assertEqual(result["badge"], "Remote Badge")
        self.assertEqual(result["title"], "Remote Title")
        self.assertEqual(result["format"], "html")
        self.assertIn("line one", result["body"])

    def test_normalize_about_falls_back_to_plain_for_unknown_format(self):
        texts = {"about_badge": "Badge", "app_name": "VideoSeek", "about_body": "Body"}

        result = about_service._normalize_about({"format": "markdown"}, texts)

        self.assertEqual(result["format"], "plain")


class VersionServiceTests(unittest.TestCase):
    def test_compare_versions_handles_numeric_order(self):
        self.assertEqual(version_service._compare_versions("1.0.10", "1.0.2"), 1)
        self.assertEqual(version_service._compare_versions("1.0.0", "1.0"), 0)
        self.assertEqual(version_service._compare_versions("1.2", "1.2.1"), -1)

    def test_parse_version_ignores_prefix_and_suffix_noise(self):
        self.assertEqual(version_service._parse_version("v1.2.3-beta1"), [1, 2, 31])

    @patch("src.services.version_service.fetch_remote_version")
    @patch("src.services.version_service.get_app_version")
    def test_get_version_status_uses_remote_download_url(self, mock_get_app_version, mock_fetch_remote_version):
        mock_get_app_version.return_value = "1.0.1"
        mock_fetch_remote_version.return_value = {
            "version": "1.0.2",
            "download_url": "https://example.com/releases",
        }

        result = version_service.get_version_status("en")

        self.assertTrue(result["has_update"])
        self.assertEqual(result["download_url"], "https://example.com/releases")


class UtilsConfigSyncTests(unittest.TestCase):
    @patch("src.app.config.save_config")
    @patch("src.app.config.load_config")
    @patch("src.utils.resolve_model_dir_info")
    @patch("src.utils.get_default_model_dir")
    @patch("src.storage.config_store.get_effective_model_dir")
    def test_sync_model_dir_to_config_writes_default_back(
        self,
        mock_get_effective_model_dir,
        mock_default_model_dir,
        mock_resolve_model_dir_info,
        mock_load_config,
        mock_save_config,
    ):
        mock_default_model_dir.return_value = "D:/VideoSeek/models"
        mock_load_config.return_value = {"model_dir": ""}
        mock_get_effective_model_dir.return_value = ""
        mock_resolve_model_dir_info.return_value = ("D:/VideoSeek/models", "default")

        result = utils.sync_model_dir_to_config()

        self.assertEqual(result, "D:/VideoSeek/models")
        self.assertEqual(mock_load_config.return_value["model_dir"], "D:/VideoSeek/models")
        mock_save_config.assert_called_once_with(mock_load_config.return_value)

    @patch("src.app.config.save_config")
    @patch("src.app.config.load_config")
    @patch("src.utils.resolve_model_dir_info")
    @patch("src.utils.get_default_model_dir")
    @patch("src.utils.os.path.isdir")
    @patch("src.storage.config_store.get_effective_model_dir")
    @patch("src.storage.config_store.get_active_model_profile")
    def test_sync_model_dir_to_config_replaces_missing_custom_path(
        self,
        mock_get_active_profile,
        mock_get_effective_model_dir,
        mock_isdir,
        mock_default_model_dir,
        mock_resolve_model_dir_info,
        mock_load_config,
        mock_save_config,
    ):
        mock_default_model_dir.return_value = "D:/VideoSeek/models"
        # Use normpath-stable path so sync_model_dir_to_config does not extra-save on slash normalization.
        missing_custom = os.path.normpath("C:/Users/LiuWei/AppData/Local/VideoSeek/models")
        mock_load_config.return_value = {"model_dir": missing_custom}
        mock_get_effective_model_dir.return_value = missing_custom
        mock_get_active_profile.return_value = {"id": "clip_onnx_default"}
        mock_isdir.return_value = False
        mock_resolve_model_dir_info.return_value = ("D:/VideoSeek/models", "default")

        result = utils.sync_model_dir_to_config()

        self.assertEqual(result, "D:/VideoSeek/models")
        self.assertEqual(mock_load_config.return_value["model_dir"], "D:/VideoSeek/models")
        self.assertEqual(mock_save_config.call_args_list[-1][0][0]["model_dir"], "D:/VideoSeek/models")

    @patch("src.app.config.save_config")
    @patch("src.app.config.load_config")
    @patch("src.utils.os.path.isdir")
    @patch("src.storage.config_store.get_effective_model_dir")
    @patch("src.storage.config_store.get_active_model_profile")
    def test_sync_model_dir_to_config_prefers_valid_top_level_when_runtime_stale(
        self,
        mock_get_active_profile,
        mock_get_effective_model_dir,
        mock_isdir,
        mock_load_config,
        mock_save_config,
    ):
        stale_runtime_dir = os.path.normpath("C:/Users/LiuWei/AppData/Local/VideoSeek/models")
        moved_model_root = os.path.normpath("D:/vsdata/models")
        config = {
            "model_dir": moved_model_root,
            "models": {
                "active_profile": "clip_onnx_default",
                "profiles": [
                    {
                        "id": "clip_onnx_default",
                        "runtime": {"model_dir": stale_runtime_dir},
                    }
                ],
            },
        }
        mock_load_config.return_value = config
        mock_get_effective_model_dir.return_value = stale_runtime_dir
        mock_get_active_profile.return_value = {"id": "clip_onnx_default"}

        def _isdir(path):
            normalized = os.path.normcase(os.path.normpath(str(path)))
            if normalized == os.path.normcase(stale_runtime_dir):
                return False
            if normalized == os.path.normcase(moved_model_root):
                return True
            return False

        mock_isdir.side_effect = _isdir

        result = utils.sync_model_dir_to_config()

        self.assertEqual(result, moved_model_root)
        self.assertEqual(config["model_dir"], moved_model_root)
        runtime_dir = config["models"]["profiles"][0]["runtime"]["model_dir"]
        self.assertEqual(runtime_dir, moved_model_root)
        mock_save_config.assert_called_once_with(config)

    @patch("src.app.config.save_config")
    @patch("src.app.config.load_config")
    @patch("src.utils.resolve_ffmpeg_path_info")
    def test_sync_ffmpeg_path_to_config_writes_detected_path(
        self,
        mock_resolve_ffmpeg_path_info,
        mock_load_config,
        mock_save_config,
    ):
        mock_load_config.return_value = {"ffmpeg_path": ""}
        mock_resolve_ffmpeg_path_info.return_value = ("D:/ffmpeg/bin/ffmpeg.exe", "system")

        result = utils.sync_ffmpeg_path_to_config()

        self.assertEqual(result, "D:/ffmpeg/bin/ffmpeg.exe")
        self.assertEqual(mock_load_config.return_value["ffmpeg_path"], "D:/ffmpeg/bin/ffmpeg.exe")
        mock_save_config.assert_called_once_with(mock_load_config.return_value)


class RuntimeDiagnosticTests(unittest.TestCase):
    @patch("src.core.clip_embedding._is_windows", return_value=True)
    @patch("src.core.clip_embedding._is_windows_10_1903_or_newer", return_value=True)
    @patch("src.core.clip_embedding._is_directml_provider_available", return_value=False)
    def test_detect_gpu_runtime_issue_reports_directml(self, _mock_provider, _mock_version, _mock_windows):
        self.assertEqual(clip_embedding.detect_gpu_runtime_issue(), "directml")

    @patch("src.core.clip_embedding._is_windows", return_value=True)
    @patch("src.core.clip_embedding._is_windows_10_1903_or_newer", return_value=True)
    @patch("src.core.clip_embedding._is_directml_provider_available", return_value=True)
    @patch("src.core.clip_embedding._can_load_windows_dll", return_value=False)
    def test_detect_gpu_runtime_issue_reports_directx(
        self,
        _mock_dll,
        _mock_provider,
        _mock_version,
        _mock_windows,
    ):
        self.assertEqual(clip_embedding.detect_gpu_runtime_issue(), "directx")

    @patch("src.core.clip_embedding._is_windows", return_value=True)
    @patch("src.core.clip_embedding._is_windows_10_1903_or_newer", return_value=True)
    @patch("src.core.clip_embedding._is_directml_provider_available", return_value=True)
    @patch("src.core.clip_embedding._can_load_windows_dll")
    def test_detect_gpu_runtime_issue_reports_msvc(
        self,
        mock_can_load_dll,
        _mock_provider,
        _mock_version,
        _mock_windows,
    ):
        def _dll_side_effect(name):
            lower = str(name or "").lower()
            if lower in ("directml.dll", "d3d12.dll"):
                return True
            return False

        mock_can_load_dll.side_effect = _dll_side_effect

        self.assertEqual(clip_embedding.detect_gpu_runtime_issue(), "msvc")


if __name__ == "__main__":
    unittest.main()
