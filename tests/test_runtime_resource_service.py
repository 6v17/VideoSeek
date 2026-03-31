import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.modules.setdefault("numpy", types.SimpleNamespace())

from src.services import runtime_resource_service


class RuntimeResourceServiceTests(unittest.TestCase):
    @patch("src.services.runtime_resource_service.get_app_meta")
    @patch("src.services.runtime_resource_service.has_ffmpeg")
    @patch("src.services.runtime_resource_service.get_default_ffmpeg_path")
    @patch("src.services.runtime_resource_service.get_configured_model_dir")
    @patch("src.services.runtime_resource_service.get_app_data_dir")
    @patch("src.services.runtime_resource_service.get_missing_model_files")
    def test_get_runtime_resource_status_includes_ffmpeg_when_missing(
        self,
        mock_missing_files,
        mock_app_data_dir,
        mock_model_dir,
        mock_ffmpeg_path,
        mock_has_ffmpeg,
        mock_get_app_meta,
    ):
        mock_missing_files.return_value = (["clip_visual.onnx"], {})
        mock_app_data_dir.return_value = "D:/VideoSeek"
        mock_model_dir.return_value = "D:/VideoSeek/models"
        mock_ffmpeg_path.return_value = "D:/VideoSeek/bin/ffmpeg.exe"
        mock_has_ffmpeg.return_value = False
        mock_get_app_meta.return_value = {"model_manifest_url": "https://example.com/manifest.json"}

        status = runtime_resource_service.get_runtime_resource_status()

        self.assertFalse(status["resources_ready"])
        self.assertEqual(status["display_files"], ["clip_visual.onnx", "ffmpeg.exe"])
        self.assertTrue(status["download_enabled"])

    def test_get_runtime_resource_location_text_can_hide_ffmpeg(self):
        status = {
            "model_dir": "D:/VideoSeek/models",
            "ffmpeg_target_path": "D:/VideoSeek/bin/ffmpeg.exe",
        }

        text = runtime_resource_service.get_runtime_resource_location_text(status=status, include_ffmpeg=False)

        self.assertEqual(text, "Models: D:/VideoSeek/models")

    @patch("src.services.runtime_resource_service.os.makedirs")
    def test_ensure_runtime_resource_dirs_creates_only_missing_targets(self, mock_makedirs):
        status = {
            "root_dir": "D:/VideoSeek",
            "model_dir": "D:/VideoSeek/models",
            "ffmpeg_target_path": "D:/VideoSeek/bin/ffmpeg.exe",
            "missing_model_files": ["clip_text.onnx"],
            "ffmpeg_ready": False,
        }

        root_dir = runtime_resource_service.ensure_runtime_resource_dirs(status=status)

        self.assertEqual(root_dir, "D:/VideoSeek")
        self.assertEqual(
            [call.args[0] for call in mock_makedirs.call_args_list],
            ["D:/VideoSeek", "D:/VideoSeek/models", "D:/VideoSeek/bin"],
        )


if __name__ == "__main__":
    unittest.main()
