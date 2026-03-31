import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.modules.setdefault("numpy", types.SimpleNamespace())

from src.services import ffmpeg_service, model_service


class DownloadManifestTests(unittest.TestCase):
    def test_model_manifest_uses_manifest_dir_when_no_base_url(self):
        manifest = model_service._normalize_manifest(
            {"files": [{"name": "clip_visual.onnx"}]},
            "https://example.com/meta/manifest.json",
        )

        self.assertEqual(
            manifest["files"][0]["sources"][0]["url"],
            "https://example.com/meta/clip_visual.onnx",
        )

    def test_model_download_tries_next_source_after_failure(self):
        calls = []

        def fake_download(url, target_path, expected_sha256="", progress_callback=None, source_label=""):
            calls.append(url)
            if "primary" in url:
                raise RuntimeError("primary failed")

        with patch("src.services.model_service._download_file", side_effect=fake_download):
            label = model_service._download_file_from_sources(
                [
                    {"label": "primary", "url": "https://primary.example.com/file.onnx"},
                    {"label": "mirror-1", "url": "https://mirror.example.com/file.onnx"},
                ],
                "D:/tmp/file.part",
            )

        self.assertEqual(label, "mirror-1")
        self.assertEqual(
            calls,
            [
                "https://primary.example.com/file.onnx",
                "https://mirror.example.com/file.onnx",
            ],
        )

    @patch("src.services.model_service.os.path.exists", return_value=False)
    def test_model_download_reports_all_source_errors(self, _mock_exists):
        with patch(
            "src.services.model_service._download_file",
            side_effect=[RuntimeError("first"), RuntimeError("second")],
        ):
            with self.assertRaises(RuntimeError) as context:
                model_service._download_file_from_sources(
                    [
                        {"label": "primary", "url": "https://a.example.com/file.onnx"},
                        {"label": "mirror-1", "url": "https://b.example.com/file.onnx"},
                    ],
                    "D:/tmp/file.part",
                )

        message = str(context.exception)
        self.assertIn("primary: first", message)
        self.assertIn("mirror-1: second", message)

    def test_ffmpeg_manifest_uses_ffmpeg_specific_base_url_and_mirrors(self):
        entry = ffmpeg_service._normalize_ffmpeg_entry(
            {
                "base_url": "https://global.example.com/models/",
                "mirrors": ["https://global-mirror.example.com/models/"],
                "ffmpeg": {
                    "name": "ffmpeg.exe",
                    "base_url": "https://oss.example.com/bin/",
                    "mirrors": [{"label": "cdn", "base_url": "https://cdn.example.com/bin/"}],
                },
            },
            "https://example.com/manifest.json",
        )

        self.assertEqual(entry["sources"][0]["url"], "https://oss.example.com/bin/ffmpeg.exe")
        self.assertEqual(entry["sources"][1]["label"], "cdn")

    def test_ffmpeg_manifest_falls_back_to_global_mirrors(self):
        entry = ffmpeg_service._normalize_ffmpeg_entry(
            {
                "mirrors": ["https://mirror.example.com/bin/"],
                "ffmpeg": {"name": "ffmpeg.exe", "base_url": "https://primary.example.com/bin/"},
            },
            "https://example.com/manifest.json",
        )

        self.assertEqual(
            [source["url"] for source in entry["sources"]],
            [
                "https://primary.example.com/bin/ffmpeg.exe",
                "https://mirror.example.com/bin/ffmpeg.exe",
            ],
        )


if __name__ == "__main__":
    unittest.main()
