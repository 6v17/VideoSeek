import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from src.services import bundled_runtime_service


class BundledRuntimeServiceTests(unittest.TestCase):
    def test_bundled_runtime_available_requires_all_manifest_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = os.path.join(temp_dir, "runtime")
            os.makedirs(runtime_dir)
            manifest = {
                "manifest_version": 1,
                "files": ["ffmpeg.exe", "chinese-clip.zip"],
            }
            with open(os.path.join(runtime_dir, "manifest.json"), "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)
            self.assertFalse(bundled_runtime_service.bundled_runtime_available(runtime_dir=runtime_dir))
            Path(runtime_dir, "ffmpeg.exe").write_bytes(b"ffmpeg")
            self.assertFalse(bundled_runtime_service.bundled_runtime_available(runtime_dir=runtime_dir))
            Path(runtime_dir, "chinese-clip.zip").write_bytes(b"zip")
            self.assertTrue(bundled_runtime_service.bundled_runtime_available(runtime_dir=runtime_dir))

    def test_bootstrap_imports_seed_zip_and_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = os.path.join(temp_dir, "VideoSeek")
            runtime_dir = os.path.join(temp_dir, "install", "runtime")
            os.makedirs(runtime_dir)
            os.makedirs(app_data)

            required_files = [
                "chinese_clip_image.onnx",
                "chinese_clip_text.onnx",
                "vocab.txt",
                "preprocessor_config.json",
                "config.json",
            ]
            package_dir = Path(runtime_dir) / "_pkg" / "chinese-clip" / "vit-base-patch16"
            package_dir.mkdir(parents=True)
            for file_name in required_files:
                (package_dir / file_name).write_bytes(b"x")
            (package_dir / "model_manifest.json").write_text(
                json.dumps(
                    {
                        "id": "chinese_clip_onnx_vit-base-patch16",
                        "provider": "chinese_clip_onnx",
                        "variant": "vit-base-patch16",
                        "display_name": "Chinese CLIP",
                        "required_files": required_files,
                    }
                ),
                encoding="utf-8",
            )
            zip_path = Path(runtime_dir) / "chinese-clip.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                for file_path in package_dir.rglob("*"):
                    if file_path.is_file():
                        archive.write(file_path, file_path.relative_to(package_dir.parent).as_posix())
            # Large enough + PE magic so has_ffmpeg() accepts the copied binary.
            Path(runtime_dir, "ffmpeg.exe").write_bytes(b"MZ" + (b"\0" * (256 * 1024)))

            manifest = {
                "manifest_version": 1,
                "prefer_active_profile_id": "chinese_clip_onnx_vit-base-patch16",
                "files": ["ffmpeg.exe", "chinese-clip.zip"],
            }
            with open(os.path.join(runtime_dir, "manifest.json"), "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)

            config = {
                "schema_version": 2,
                "model_dir": os.path.join(app_data, "models"),
                "ffmpeg_path": os.path.join(app_data, "bin", "ffmpeg.exe"),
                "models": {"active_profile": "", "profiles": []},
            }

            def _load_config():
                return config

            with (
                patch("src.services.bundled_runtime_service.get_bundled_runtime_dir", return_value=runtime_dir),
                # Bound imports: patch where each module looks up get_app_data_dir.
                patch("src.services.runtime_resource_service.get_app_data_dir", return_value=app_data),
                patch("src.infra.ffmpeg_paths.get_app_data_dir", return_value=app_data),
                patch("src.utils.get_app_data_dir", return_value=app_data),
                patch("src.app.config.load_config", side_effect=_load_config),
                patch("src.app.config.save_config") as save_config,
                patch("src.services.model_package_service.load_config", side_effect=_load_config),
                patch("src.services.model_package_service.save_config"),
                patch("src.services.model_package_service.get_config_schema_version", return_value=2),
                patch("src.services.runtime_resource_service.load_config", side_effect=_load_config),
            ):
                result = bundled_runtime_service.bootstrap_bundled_runtime()

            self.assertTrue(result.get("ok"), msg=result)
            self.assertTrue(save_config.called)
            status = result.get("status") or {}
            self.assertTrue(status.get("ffmpeg_ready"))
            self.assertTrue(status.get("model_ready"))
            self.assertTrue(Path(app_data, "bin", "ffmpeg.exe").is_file())
            model_manifest = Path(app_data, "models", "chinese-clip", "vit-base-patch16", "model_manifest.json")
            self.assertTrue(model_manifest.is_file())

    def test_plan_supplemental_imports_missing_chinese_clip_without_switching_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = os.path.join(temp_dir, "runtime")
            app_data = os.path.join(temp_dir, "VideoSeek")
            model_root = os.path.join(app_data, "models")
            os.makedirs(runtime_dir)
            Path(runtime_dir, "ffmpeg.exe").write_bytes(b"ffmpeg")
            Path(runtime_dir, "chinese-clip.zip").write_bytes(b"zip")
            Path(runtime_dir, "rapidocr-zh-understanding.zip").write_bytes(b"ocr")
            with open(os.path.join(runtime_dir, "manifest.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "files": ["ffmpeg.exe", "chinese-clip.zip", "rapidocr-zh-understanding.zip"],
                        "prefer_active_profile_id": "chinese_clip_onnx_vit-base-patch16",
                    },
                    handle,
                )
            openai_dir = Path(model_root) / "openai-clip" / "vit-base-patch32"
            openai_dir.mkdir(parents=True)
            for name in ("clip_visual.onnx", "clip_text.onnx", "bpe_simple_vocab_16e6.txt.gz"):
                (openai_dir / name).write_bytes(b"x")
            (openai_dir / "model_manifest.json").write_text(
                json.dumps({"provider": "clip_onnx", "variant": "vit-base-patch32"}),
                encoding="utf-8",
            )
            ffmpeg_target = os.path.join(app_data, "bin", "ffmpeg.exe")
            os.makedirs(os.path.dirname(ffmpeg_target), exist_ok=True)
            Path(ffmpeg_target).write_bytes(b"ffmpeg")

            ready_status = {
                "resources_ready": True,
                "model_ready": True,
                "ffmpeg_ready": True,
                "model_root_dir": model_root,
                "model_dir": model_root,
            }

            with (
                patch("src.services.bundled_runtime_service.get_bundled_runtime_dir", return_value=runtime_dir),
                patch("src.services.runtime_resource_service.get_runtime_resource_status", return_value=ready_status),
                patch("src.services.bundled_runtime_service.is_bundled_rapidocr_installed", return_value=True),
                patch("src.utils.has_ffmpeg", return_value=True),
            ):
                plan = bundled_runtime_service.plan_bundled_import(runtime_dir=runtime_dir)

            self.assertTrue(plan.get("supplemental"))
            self.assertFalse(plan.get("switch_active_profile"))
            names = {os.path.basename(path).lower() for path in plan.get("paths") or []}
            self.assertIn("chinese-clip.zip", names)
            self.assertNotIn("ffmpeg.exe", names)
            self.assertNotIn("rapidocr-zh-understanding.zip", names)


if __name__ == "__main__":
    unittest.main()
