import tempfile
import unittest
import os
import zipfile
import json
from pathlib import Path
from unittest.mock import patch

import tests.services_test_support  # noqa: F401 - cv2/faiss stubs
from src.services import model_service
from src.services import model_package_service


class ModelServiceTests(unittest.TestCase):
    def test_normalize_manifest_uses_base_url_for_missing_file_urls(self):
        manifest = model_service._normalize_manifest(
            {
                "version": "v1",
                "base_url": "https://example.com/models/",
                "files": [{"name": "clip_visual.onnx"}],
            },
            "https://example.com/manifest.json",
        )

        self.assertEqual(manifest["version"], "v1")
        self.assertEqual(
            manifest["files"][0]["sources"][0]["url"],
            "https://example.com/models/clip_visual.onnx",
        )

    def test_normalize_manifest_includes_mirrors(self):
        manifest = model_service._normalize_manifest(
            {
                "base_url": "https://primary.example.com/models/",
                "mirrors": [
                    {"label": "cdn", "base_url": "https://cdn.example.com/models/"},
                    "https://mirror.example.com/models/",
                ],
                "files": [{"name": "clip_visual.onnx"}],
            },
            "https://example.com/manifest.json",
        )

        sources = manifest["files"][0]["sources"]
        self.assertEqual(len(sources), 3)
        self.assertEqual(sources[1]["label"], "cdn")
        self.assertEqual(sources[2]["url"], "https://mirror.example.com/models/clip_visual.onnx")

    def test_normalize_manifest_respects_file_sources(self):
        manifest = model_service._normalize_manifest(
            {
                "base_url": "https://primary.example.com/models/",
                "files": [
                    {
                        "name": "clip_visual.onnx",
                        "sources": [
                            {"label": "oss", "base_url": "https://oss.example.com/models/"},
                            {"label": "github", "url": "https://github.com/example/clip_visual.onnx"},
                        ],
                    }
                ],
            },
            "https://example.com/manifest.json",
        )

        sources = manifest["files"][0]["sources"]
        self.assertEqual(sources[0]["url"], "https://oss.example.com/models/clip_visual.onnx")
        self.assertEqual(sources[1]["label"], "github")



class ModelPackageServiceTests(unittest.TestCase):
    def test_import_updates_legacy_default_profile_with_empty_variant(self):
        with tempfile.TemporaryDirectory() as model_root:
            manifest_dir = Path(model_root) / "openai-clip" / "vit-base-patch32"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "clip_visual.onnx").write_bytes(b"dummy")
            (manifest_dir / "model_manifest.json").write_text(
                json.dumps(
                    {
                        "id": "clip_onnx_default",
                        "provider": "clip_onnx",
                        "variant": "vit-base-patch32",
                        "display_name": "CLIP ONNX",
                        "required_files": ["clip_visual.onnx"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            config = {
                "models": {
                    "active_profile": "clip_onnx_default",
                    "profiles": [
                        {
                            "id": "clip_onnx_default",
                            "provider": "clip_onnx",
                            "display_name": "CLIP ONNX",
                            "enabled": True,
                            "runtime": {
                                "prefer_gpu": True,
                                "model_dir": model_root,
                                "model_variant": "",
                            },
                            "files": {"visual_model": "clip_visual.onnx"},
                        }
                    ],
                }
            }

            with (
                patch("src.services.model_package_service.load_config", return_value=config),
                patch("src.services.model_package_service.save_config") as mock_save_config,
                patch("src.services.model_package_service.get_config_schema_version", return_value=2),
            ):
                result = model_package_service.import_model_packages(model_root)

            self.assertEqual(result["imported"], 0)
            self.assertEqual(result["updated"], 1)
            self.assertEqual(result["errors"], [])
            self.assertTrue(mock_save_config.called)
            self.assertEqual(config["models"]["profiles"][0]["runtime"]["model_variant"], "vit-base-patch32")

    def test_import_switches_active_profile_when_placeholder_clip_is_not_ready(self):
        with tempfile.TemporaryDirectory() as model_root:
            manifest_dir = Path(model_root) / "chinese-clip" / "vit-base-patch16"
            manifest_dir.mkdir(parents=True)
            required_files = [
                "chinese_clip_image.onnx",
                "chinese_clip_text.onnx",
                "vocab.txt",
                "preprocessor_config.json",
                "config.json",
            ]
            for file_name in required_files:
                (manifest_dir / file_name).write_bytes(b"x")
            (manifest_dir / "model_manifest.json").write_text(
                json.dumps(
                    {
                        "id": "chinese_clip_vit_base_patch16",
                        "provider": "chinese_clip_onnx",
                        "variant": "vit-base-patch16",
                        "display_name": "Chinese CLIP",
                        "required_files": required_files,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            config = {
                "models": {
                    "active_profile": "clip_onnx_default",
                    "profiles": [
                        {
                            "id": "clip_onnx_default",
                            "provider": "clip_onnx",
                            "display_name": "OpenAI CLIP",
                            "enabled": True,
                            "runtime": {
                                "prefer_gpu": True,
                                "model_dir": model_root,
                                "model_variant": "vit-base-patch32",
                            },
                            "files": {
                                "visual_model": "clip_visual.onnx",
                                "text_model": "clip_text.onnx",
                                "tokenizer_vocab": "bpe_simple_vocab_16e6.txt.gz",
                            },
                        }
                    ],
                }
            }

            with (
                patch("src.services.model_package_service.load_config", return_value=config),
                patch("src.services.model_package_service.save_config") as mock_save_config,
                patch("src.services.model_package_service.get_config_schema_version", return_value=2),
            ):
                result = model_package_service.import_model_packages(model_root)

            self.assertEqual(result["imported"], 1)
            self.assertEqual(result["updated"], 0)
            self.assertTrue(result["active_profile_switched"])
            self.assertEqual(result["active_profile"], "chinese_clip_vit_base_patch16")
            self.assertEqual(config["models"]["active_profile"], "chinese_clip_vit_base_patch16")
            self.assertTrue(mock_save_config.called)

    def test_import_model_package_zip_ignores_unrelated_placeholder_manifests(self):
        with tempfile.TemporaryDirectory() as model_root:
            placeholder_dir = Path(model_root) / "openai-clip" / "vit-base-patch32"
            placeholder_dir.mkdir(parents=True)
            (placeholder_dir / "model_manifest.json").write_text(
                json.dumps(
                    {
                        "id": "clip_onnx_default",
                        "provider": "clip_onnx",
                        "variant": "vit-base-patch32",
                        "required_files": ["clip_visual.onnx", "clip_text.onnx"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            required_files = [
                "chinese_clip_image.onnx",
                "chinese_clip_text.onnx",
                "vocab.txt",
                "preprocessor_config.json",
                "config.json",
            ]
            zip_root = Path(model_root) / "packages"
            zip_root.mkdir()
            package_dir = zip_root / "chinese-clip" / "vit-base-patch16"
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
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            zip_path = zip_root / "chinese_clip.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                for file_path in package_dir.rglob("*"):
                    if file_path.is_file():
                        archive.write(file_path, file_path.relative_to(package_dir.parent).as_posix())

            config = {
                "models": {
                    "active_profile": "clip_onnx_default",
                    "profiles": [
                        {
                            "id": "clip_onnx_default",
                            "provider": "clip_onnx",
                            "display_name": "OpenAI CLIP",
                            "enabled": True,
                            "runtime": {
                                "prefer_gpu": True,
                                "model_dir": model_root,
                                "model_variant": "vit-base-patch32",
                            },
                            "files": {
                                "visual_model": "clip_visual.onnx",
                                "text_model": "clip_text.onnx",
                                "tokenizer_vocab": "bpe_simple_vocab_16e6.txt.gz",
                            },
                        }
                    ],
                }
            }

            with (
                patch("src.services.model_package_service.load_config", return_value=config),
                patch("src.services.model_package_service.save_config"),
                patch("src.services.model_package_service.get_config_schema_version", return_value=2),
            ):
                result = model_package_service.import_model_package_zip(model_root, str(zip_path))

            self.assertEqual(result["imported"], 1)
            self.assertEqual(result["errors"], [])



class ModelResourceDirTests(unittest.TestCase):
    def test_resolve_model_resource_dir_prefers_legacy_chinese_clip_onnx_folder(self):
        from src.storage.config_store import resolve_model_resource_dir

        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_dir = os.path.join(temp_dir, "chinese-clip-onnx", "vit-base-patch16")
            os.makedirs(legacy_dir, exist_ok=True)
            marker = os.path.join(legacy_dir, "chinese_clip_text.onnx")
            with open(marker, "wb") as handle:
                handle.write(b"onnx")

            resolved = resolve_model_resource_dir(temp_dir, "chinese_clip_onnx", "vit-base-patch16")

            self.assertEqual(os.path.normcase(resolved), os.path.normcase(legacy_dir))


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
