import json
import os
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.modules.setdefault("numpy", types.SimpleNamespace())

from src.services import runtime_resource_service


class RuntimeResourceServiceTests(unittest.TestCase):
    @patch("src.services.runtime_resource_service.get_app_meta")
    @patch("src.services.runtime_resource_service.has_ffmpeg")
    @patch("src.services.runtime_resource_service.get_configured_ffmpeg_target_path")
    @patch("src.services.runtime_resource_service.get_active_model_resource_dir")
    @patch("src.services.runtime_resource_service.get_app_data_dir")
    @patch("src.services.runtime_resource_service.get_missing_model_files")
    def test_get_runtime_resource_status_includes_ffmpeg_when_missing(
        self,
        mock_missing_files,
        mock_app_data_dir,
        mock_active_model_resource_dir,
        mock_ffmpeg_target_path,
        mock_has_ffmpeg,
        mock_get_app_meta,
    ):
        mock_missing_files.return_value = (["clip_visual.onnx"], {})
        mock_app_data_dir.return_value = "D:/VideoSeek"
        mock_active_model_resource_dir.return_value = "D:/VideoSeek/models"
        mock_ffmpeg_target_path.return_value = "D:/VideoSeek/bin/ffmpeg.exe"
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

        open_paths = runtime_resource_service.ensure_runtime_resource_dirs(status=status)

        self.assertEqual(
            open_paths,
            [
                os.path.normpath("D:/VideoSeek/models"),
                os.path.normpath("D:/VideoSeek/bin"),
            ],
        )
        self.assertEqual(
            [os.path.normpath(call.args[0]) for call in mock_makedirs.call_args_list],
            [
                os.path.normpath("D:/VideoSeek"),
                os.path.normpath("D:/VideoSeek/models"),
                os.path.normpath("D:/VideoSeek/bin"),
            ],
        )

    @patch("src.app.config.save_config")
    def test_install_ffmpeg_executable_copies_to_configured_target(self, mock_save_config):
        from src.infra.ffmpeg_paths import install_ffmpeg_executable

        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "ffmpeg.exe")
            target = os.path.join(temp_dir, "bin", "ffmpeg.exe")
            with open(source, "wb") as handle:
                handle.write(b"ffmpeg-bytes")
            config = {"ffmpeg_path": target, "model_dir": temp_dir}

            installed = install_ffmpeg_executable(source, config=config)

            self.assertEqual(os.path.normpath(installed), os.path.normpath(target))
            self.assertEqual(config["ffmpeg_path"], os.path.normpath(target))
            self.assertEqual(Path(target).read_bytes(), b"ffmpeg-bytes")
            mock_save_config.assert_called_once_with(config)

    def test_import_runtime_resources_rejects_unknown_files(self):
        with self.assertRaises(RuntimeError):
            runtime_resource_service.import_runtime_resources(["D:/downloads/notes.txt"])

    def test_import_selected_runtime_packages_installs_search_zip(self):
        with tempfile.TemporaryDirectory() as model_root:
            required_files = [
                "chinese_clip_image.onnx",
                "chinese_clip_text.onnx",
                "vocab.txt",
                "preprocessor_config.json",
                "config.json",
            ]
            package_dir = Path(model_root) / "staging" / "chinese-clip" / "vit-base-patch16"
            package_dir.mkdir(parents=True)
            for file_name in required_files:
                (package_dir / file_name).write_bytes(b"x")
            (package_dir / "model_manifest.json").write_text(
                json.dumps(
                    {
                        "id": "chinese_clip_vit_base_patch16",
                        "provider": "chinese_clip_onnx",
                        "variant": "vit-base-patch16",
                        "display_name": "Chinese CLIP",
                        "required_files": required_files,
                    }
                ),
                encoding="utf-8",
            )
            zip_path = Path(model_root) / "chinese_clip.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                for file_path in package_dir.rglob("*"):
                    if file_path.is_file():
                        archive.write(file_path, file_path.relative_to(package_dir.parent).as_posix())

            config = {
                "models": {
                    "active_profile": "",
                    "profiles": [],
                }
            }
            with (
                patch("src.services.model_package_service.load_config", return_value=config),
                patch("src.services.model_package_service.save_config"),
                patch("src.services.model_package_service.get_config_schema_version", return_value=2),
            ):
                result = runtime_resource_service.import_selected_runtime_packages(model_root, [str(zip_path)])

            self.assertEqual(result["imported"], 1)
            self.assertEqual(result["errors"], [])
            self.assertTrue((Path(model_root) / "chinese-clip" / "vit-base-patch16" / "model_manifest.json").is_file())


def _load_import_script():
    import importlib.util

    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "import_runtime_resources.py")
    spec = importlib.util.spec_from_file_location("import_runtime_resources_under_test", os.path.abspath(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StandaloneRuntimeImportTests(unittest.TestCase):
    def test_standalone_import_writes_installed_app_data(self):
        script = _load_import_script()
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = os.path.join(temp_dir, "VideoSeek")
            os.makedirs(app_data)
            with open(os.path.join(app_data, "config.json"), "w", encoding="utf-8") as handle:
                json.dump({"schema_version": 2, "library_paths": ["D:/videos"]}, handle)

            search_dir = Path(temp_dir) / "openai-clip" / "vit-large-patch14"
            search_dir.mkdir(parents=True)
            (search_dir / "clip_visual.onnx").write_bytes(b"v")
            (search_dir / "model_manifest.json").write_text(
                json.dumps(
                    {
                        "id": "clip_onnx_vit_large_patch14",
                        "provider": "clip_onnx",
                        "variant": "vit-large-patch14",
                        "display_name": "OpenAI CLIP",
                    }
                ),
                encoding="utf-8",
            )
            search_zip = Path(temp_dir) / "openai-clip.zip"
            with zipfile.ZipFile(search_zip, "w") as archive:
                for file_path in search_dir.rglob("*"):
                    if file_path.is_file():
                        archive.write(file_path, file_path.relative_to(search_dir.parent).as_posix())

            ocr_dir = Path(temp_dir) / "ocr"
            ocr_dir.mkdir()
            (ocr_dir / "ch_PP-OCRv4_det_infer.onnx").write_bytes(b"d")
            (ocr_dir / "understanding_manifest.json").write_text(
                json.dumps(
                    {
                        "id": "vision/ocr/rapidocr-zh",
                        "install_relpath": "components/vision/ocr/rapidocr-zh",
                    }
                ),
                encoding="utf-8",
            )
            ocr_zip = Path(temp_dir) / "rapidocr-zh-understanding.zip"
            with zipfile.ZipFile(ocr_zip, "w") as archive:
                for file_path in ocr_dir.iterdir():
                    archive.write(file_path, file_path.name)

            ffmpeg = Path(temp_dir) / "ffmpeg.exe"
            ffmpeg.write_bytes(b"ffmpeg")

            payload = script.import_runtime_resources_standalone(
                [str(search_zip), str(ocr_zip), str(ffmpeg)],
                app_data_dir=app_data,
            )

            config = json.loads(Path(payload["config_file"]).read_text(encoding="utf-8"))
            self.assertEqual(config["library_paths"], ["D:/videos"])
            self.assertEqual(config["models"]["active_profile"], "clip_onnx_vit_large_patch14")
            self.assertTrue(os.path.isfile(config["ffmpeg_path"]))
            self.assertTrue(
                (
                    Path(app_data)
                    / "models"
                    / "understanding"
                    / "components"
                    / "vision"
                    / "ocr"
                    / "rapidocr-zh"
                    / "understanding_manifest.json"
                ).is_file()
            )
            self.assertEqual(payload["packages"]["errors"], [])
            self.assertEqual(payload["packages"]["understanding_imported"], ["vision/ocr/rapidocr-zh"])


if __name__ == "__main__":
    unittest.main()
