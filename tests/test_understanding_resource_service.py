import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from src.app.config import DEFAULT_UNDERSTANDING_CONFIG
from src.services import understanding_import_service, understanding_resource_service


YOLO_MANIFEST = {
    "kind": "understanding_component",
    "manifest_version": 1,
    "id": "vision/object_detection/yolo11n",
    "modality": "vision",
    "task": "object_detection",
    "model_id": "yolo11n",
    "display_name": "YOLO11n Object Detection (ONNX)",
    "install_relpath": "components/vision/object_detection/yolo11n",
    "input_kind": "chunk_keyframe",
    "output_kind": "objects",
    "engine": {"registry_key": "vision.object_detection.yolo11n"},
    "required_files": ["yolo11n.onnx"],
    "files": {"model": "yolo11n.onnx"},
}

CAPTION_MANIFEST = {
    "kind": "understanding_component",
    "manifest_version": 1,
    "id": "vision/image_caption/vit-gpt2-quantized",
    "modality": "vision",
    "task": "image_caption",
    "model_id": "vit-gpt2-quantized",
    "display_name": "ViT-GPT2 Image Caption (ONNX quantized)",
    "install_relpath": "components/vision/image_caption/vit-gpt2-quantized",
    "input_kind": "chunk_keyframe",
    "output_kind": "caption",
    "engine": {"registry_key": "vision.image_caption.vit_gpt2_quantized"},
    "required_files": ["encoder_model_quantized.onnx"],
    "files": {"encoder": "encoder_model_quantized.onnx"},
}


def _write_component_zip(zip_path: Path, manifest: dict, payload_name: str) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("understanding_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr(payload_name, b"dummy-model")


class UnderstandingImportServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.model_root = Path(self.temp_dir.name) / "models"
        self.model_root.mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_import_single_component_zip(self):
        zip_path = self.model_root / "vision-object-detection-yolo11n.zip"
        _write_component_zip(zip_path, YOLO_MANIFEST, "yolo11n.onnx")

        result = understanding_import_service.import_understanding_component_zip(str(self.model_root), str(zip_path))

        self.assertEqual(result["component_id"], "vision/object_detection/yolo11n")
        install_dir = Path(result["install_dir"])
        self.assertTrue((install_dir / "understanding_manifest.json").is_file())
        self.assertTrue((install_dir / "yolo11n.onnx").is_file())
        self.assertTrue(result["imported"])
        self.assertFalse(result["updated"])

    def test_import_two_component_zips(self):
        yolo_zip = self.model_root / "vision-object-detection-yolo11n.zip"
        caption_zip = self.model_root / "vision-image-caption-vit-gpt2-quantized.zip"
        _write_component_zip(yolo_zip, YOLO_MANIFEST, "yolo11n.onnx")
        _write_component_zip(caption_zip, CAPTION_MANIFEST, "encoder_model_quantized.onnx")

        result = understanding_import_service.import_understanding_component_zips(
            str(self.model_root),
            [str(yolo_zip), str(caption_zip)],
        )

        self.assertEqual(
            sorted(result["imported"]),
            [
                "vision/image_caption/vit-gpt2-quantized",
                "vision/object_detection/yolo11n",
            ],
        )
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["components"]), 2)

    def test_import_rejects_invalid_kind(self):
        zip_path = self.model_root / "invalid.zip"
        invalid_manifest = dict(YOLO_MANIFEST)
        invalid_manifest["kind"] = "model_profile"
        _write_component_zip(zip_path, invalid_manifest, "yolo11n.onnx")

        with self.assertRaises(RuntimeError):
            understanding_import_service.import_understanding_component_zip(str(self.model_root), str(zip_path))

    def test_import_rejects_nested_manifest(self):
        zip_path = self.model_root / "nested.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("understanding_manifest.json", json.dumps(YOLO_MANIFEST))
            archive.writestr("nested/understanding_manifest.json", json.dumps(YOLO_MANIFEST))
            archive.writestr("yolo11n.onnx", b"dummy-model")

        with self.assertRaises(RuntimeError):
            understanding_import_service.import_understanding_component_zip(str(self.model_root), str(zip_path))

    def test_import_continue_on_error(self):
        good_zip = self.model_root / "good.zip"
        bad_zip = self.model_root / "bad.zip"
        _write_component_zip(good_zip, YOLO_MANIFEST, "yolo11n.onnx")
        _write_component_zip(bad_zip, {"kind": "understanding_component"}, "yolo11n.onnx")

        result = understanding_import_service.import_understanding_component_zips(
            str(self.model_root),
            [str(bad_zip), str(good_zip)],
            continue_on_error=True,
        )

        self.assertEqual(result["imported"], ["vision/object_detection/yolo11n"])
        self.assertEqual(len(result["errors"]), 1)

    def test_import_verifies_checksum(self):
        zip_path = self.model_root / "vision-object-detection-yolo11n.zip"
        _write_component_zip(zip_path, YOLO_MANIFEST, "yolo11n.onnx")
        digest = understanding_import_service._sha256_file(str(zip_path))
        sha_path = self.model_root / "vision-object-detection-yolo11n.zip.sha256"
        sha_path.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")

        result = understanding_import_service.import_understanding_component_zip(
            str(self.model_root),
            str(zip_path),
            sha256_file=str(sha_path),
        )

        self.assertTrue(result["checksum_verified"])


    def test_classify_package_zip(self):
        yolo_zip = self.model_root / "yolo11.zip"
        _write_component_zip(yolo_zip, YOLO_MANIFEST, "yolo11n.onnx")
        self.assertEqual(understanding_import_service.classify_package_zip(str(yolo_zip)), "understanding")

        search_zip = self.model_root / "clip.zip"
        with zipfile.ZipFile(search_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("openai-clip/vit-base-patch32/model_manifest.json", "{}")
            archive.writestr("openai-clip/vit-base-patch32/clip_visual.onnx", b"x")
        self.assertEqual(understanding_import_service.classify_package_zip(str(search_zip)), "search")


class UnderstandingResourceServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.model_root = self.root / "models"
        self.model_root.mkdir(parents=True)
        self.builtin_profiles = self.root / "resources" / "understanding_profiles" / "vision_baseline_v1"
        self.builtin_profiles.mkdir(parents=True)
        shutil.copyfile(
            Path("resources/understanding_profiles/vision_baseline_v1/profile_manifest.json"),
            self.builtin_profiles / "profile_manifest.json",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _install_component(self, manifest: dict, payload_name: str) -> None:
        install_relpath = manifest["install_relpath"].replace("/", os.sep)
        target_dir = self.model_root / "understanding" / install_relpath
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "understanding_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (target_dir / payload_name).write_bytes(b"dummy-model")

    def test_normalize_understanding_config_uses_defaults(self):
        normalized = understanding_resource_service.normalize_understanding_config({})
        self.assertEqual(
            normalized["understanding"]["active_profile"],
            DEFAULT_UNDERSTANDING_CONFIG["active_profile"],
        )
        self.assertEqual(len(normalized["understanding"]["profiles"]), 1)

    def test_scan_understanding_components_reports_missing_files(self):
        install_relpath = YOLO_MANIFEST["install_relpath"].replace("/", os.sep)
        target_dir = self.model_root / "understanding" / install_relpath
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "understanding_manifest.json").write_text(
            json.dumps(YOLO_MANIFEST, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        components = understanding_resource_service.scan_understanding_components(str(self.model_root))

        self.assertEqual(len(components), 1)
        self.assertFalse(components[0]["installed"])
        self.assertIn("missing required files", components[0]["error"])

    def test_understanding_ready_false_when_components_missing(self):
        config = {"understanding": DEFAULT_UNDERSTANDING_CONFIG}
        with (
            patch(
                "src.services.understanding_resource_service.get_configured_model_dir",
                return_value=str(self.model_root),
            ),
            patch(
                "src.services.understanding_resource_service.get_builtin_profiles_dir",
                return_value=str(self.builtin_profiles.parent),
            ),
            patch(
                "src.services.understanding_resource_service.load_profile_manifest",
                return_value=understanding_resource_service.validate_profile_manifest(
                    json.loads((self.builtin_profiles / "profile_manifest.json").read_text(encoding="utf-8")),
                    profile_dir=str(self.builtin_profiles),
                ),
            ),
        ):
            status = understanding_resource_service.get_understanding_resource_status(config=config)

        self.assertFalse(status["understanding_ready"])
        self.assertEqual(status["active_understanding_profile"], "vision_baseline_v1")
        self.assertEqual(len(status["missing_components"]), 2)

    def test_understanding_ready_true_when_profile_components_installed(self):
        self._install_component(YOLO_MANIFEST, "yolo11n.onnx")
        self._install_component(CAPTION_MANIFEST, "encoder_model_quantized.onnx")
        config = {"understanding": DEFAULT_UNDERSTANDING_CONFIG}

        with (
            patch(
                "src.services.understanding_resource_service.get_configured_model_dir",
                return_value=str(self.model_root),
            ),
            patch(
                "src.services.understanding_resource_service.get_builtin_profiles_dir",
                return_value=str(self.builtin_profiles.parent),
            ),
        ):
            status = understanding_resource_service.get_understanding_resource_status(config=config)

        self.assertTrue(status["understanding_ready"])
        self.assertEqual(status["missing_components"], [])
        self.assertEqual(len(status["installed_components"]), 2)

    def test_ensure_understanding_profiles_installed_copies_builtin_profile(self):
        with patch(
            "src.services.understanding_resource_service.get_builtin_profiles_dir",
            return_value=str(self.builtin_profiles.parent),
        ):
            installed = understanding_resource_service.ensure_understanding_profiles_installed(str(self.model_root))

        self.assertEqual(installed, ["vision_baseline_v1"])
        installed_manifest = self.model_root / "understanding" / "profiles" / "vision_baseline_v1" / "profile_manifest.json"
        self.assertTrue(installed_manifest.is_file())


if __name__ == "__main__":
    unittest.main()
