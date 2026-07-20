import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.modules.setdefault("cv2", object())
sys.modules.setdefault("numpy", object())

from src.services import storage_service


class StorageServiceTests(unittest.TestCase):
    def test_cleanup_old_data_root_removes_app_data_and_models_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_root = root / "old"
            (old_root / "data" / "vector").mkdir(parents=True)
            (old_root / "data" / "meta.json").write_text('{"libraries": {}}', encoding="utf-8")
            (old_root / "models").mkdir(parents=True)
            (old_root / "models" / "clip.onnx").write_bytes(b"model")
            (old_root / "logs").mkdir(parents=True)
            (old_root / "logs" / "app.log").write_text("log", encoding="utf-8")

            result = storage_service.cleanup_old_data_root(str(old_root), active_data_root=str(root / "active"))

            self.assertTrue(result["cleaned"])
            self.assertFalse((old_root / "data").exists())
            self.assertFalse((old_root / "models").exists())
            self.assertTrue((old_root / "logs" / "app.log").exists())

    def test_cleanup_old_data_root_rejects_active_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with self.assertRaises(ValueError):
                storage_service.cleanup_old_data_root(str(root), active_data_root=str(root))

    def test_migrate_app_data_root_copies_source_tree_and_updates_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_root = root / "current"
            current_data = current_root / "data"
            (current_data / "vector").mkdir(parents=True)
            (current_data / "meta.json").write_text('{"libraries": {}}', encoding="utf-8")
            (current_data / "vector" / "sample.npy").write_bytes(b"vector-data")
            target_root = root / "target"

            config = {
                "data_root": str(current_root),
                "meta_file": str(current_data / "meta.json"),
            }
            saved_configs = []
            progress_events = []

            with (
                patch("src.services.storage_service.load_config", return_value=config),
                patch("src.services.storage_service.save_config", side_effect=saved_configs.append),
            ):
                result = storage_service.migrate_app_data_root(
                    str(target_root),
                    progress_callback=lambda pct, msg: progress_events.append((pct, msg)),
                )

            self.assertTrue(result["migrated"])
            self.assertEqual(result.get("transfer_mode"), "move")
            self.assertFalse(result.get("old_remaining"))
            self.assertTrue((target_root / "data" / "meta.json").exists())
            self.assertTrue((target_root / "data" / "vector" / "sample.npy").exists())
            self.assertEqual(saved_configs[0]["data_root"], str(target_root))
            self.assertFalse((current_root / "data").exists())
            self.assertTrue(progress_events)
            self.assertEqual(progress_events[-1][0], 100)
            self.assertTrue(any(0 < pct < 100 for pct, _msg in progress_events))

    def test_migrate_app_data_root_rejects_nested_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_root = root / "current"
            (current_root / "data").mkdir(parents=True)
            config = {
                "data_root": str(current_root),
                "meta_file": str(current_root / "data" / "meta.json"),
            }

            with patch("src.services.storage_service.load_config", return_value=config):
                with self.assertRaises(ValueError):
                    storage_service.migrate_app_data_root(str(current_root / "child"))

    def test_migrate_app_data_root_returns_same_path_without_saving(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            current_root = Path(temp_dir)
            config = {
                "data_root": str(current_root),
                "meta_file": str(current_root / "data" / "meta.json"),
            }

            with (
                patch("src.services.storage_service.load_config", return_value=config),
                patch("src.services.storage_service.save_config") as mock_save_config,
            ):
                result = storage_service.migrate_app_data_root(str(current_root))

            self.assertFalse(result["migrated"])
            self.assertEqual(result["reason"], "same_path")
            mock_save_config.assert_not_called()

    def test_migrate_app_data_root_validates_copied_metadata_before_saving(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_root = root / "current"
            current_data = current_root / "data"
            current_data.mkdir(parents=True)
            (current_data / "meta.json").write_text("{not-json", encoding="utf-8")
            target_root = root / "target"
            config = {
                "data_root": str(current_root),
                "meta_file": str(current_data / "meta.json"),
            }

            with (
                patch("src.services.storage_service.load_config", return_value=config),
                patch("src.services.storage_service.save_config") as mock_save_config,
            ):
                with self.assertRaises(RuntimeError):
                    storage_service.migrate_app_data_root(str(target_root))

            self.assertFalse((target_root / "data").exists())
            self.assertFalse((target_root / ".videoseek-migrate-staging").exists())
            mock_save_config.assert_not_called()

    def test_migrate_app_data_root_allows_retry_after_failed_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_root = root / "current"
            current_data = current_root / "data"
            current_data.mkdir(parents=True)
            meta_file = current_data / "meta.json"
            meta_file.write_text("{not-json", encoding="utf-8")
            target_root = root / "target"
            config = {
                "data_root": str(current_root),
                "meta_file": str(meta_file),
            }
            saved_configs = []

            with (
                patch("src.services.storage_service.load_config", return_value=config),
                patch("src.services.storage_service.save_config", side_effect=saved_configs.append),
            ):
                with self.assertRaises(RuntimeError):
                    storage_service.migrate_app_data_root(str(target_root))
                meta_file.write_text('{"libraries": {}}', encoding="utf-8")
                result = storage_service.migrate_app_data_root(str(target_root))

            self.assertTrue(result["migrated"])
            self.assertTrue((target_root / "data" / "meta.json").exists())
            self.assertFalse((target_root / ".videoseek-migrate-staging").exists())
            self.assertEqual(saved_configs[-1]["data_root"], str(target_root))

    def test_migrate_app_data_root_copies_from_configured_storage_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_root = root / "current"
            actual_root = root / "actual-store"
            actual_data = actual_root / "data"
            (actual_data / "vector").mkdir(parents=True)
            (actual_data / "index").mkdir(parents=True)
            (actual_data / "meta.json").write_text('{"libraries": {}}', encoding="utf-8")
            (actual_data / "vector" / "sample.npy").write_bytes(b"vector-data")
            (actual_data / "index" / "sample.faiss").write_bytes(b"index-data")
            target_root = root / "target"

            config = {
                "data_root": str(current_root),
                "meta_file": str(actual_data / "meta.json"),
                "vector_dir": str(actual_data / "vector"),
                "index_dir": str(actual_data / "index"),
            }
            saved_configs = []

            with (
                patch("src.services.storage_service.load_config", return_value=config),
                patch("src.services.storage_service.save_config", side_effect=saved_configs.append),
                patch("src.services.storage_service.get_configured_data_root", return_value=str(current_root)),
            ):
                result = storage_service.migrate_app_data_root(str(target_root))

            self.assertTrue(result["migrated"])
            self.assertTrue((target_root / "data" / "meta.json").exists())
            self.assertTrue((target_root / "data" / "vector" / "sample.npy").exists())
            self.assertTrue((target_root / "data" / "index" / "sample.faiss").exists())
            self.assertEqual(saved_configs[0]["data_root"], str(target_root))

    def test_migrate_app_data_root_copies_app_cache_subdirectories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_root = root / "current"
            current_data = current_root / "data"
            (current_data / "remote").mkdir(parents=True)
            (current_data / "remote_build_cache").mkdir(parents=True)
            (current_data / "link_cache").mkdir(parents=True)
            (current_data / "cache").mkdir(parents=True)
            (current_data / "mobile_uploads").mkdir(parents=True)
            (current_data / "meta.json").write_text('{"libraries": {}}', encoding="utf-8")
            (current_data / "remote" / "build_report.json").write_text('{"ok": true}', encoding="utf-8")
            (current_data / "remote_build_cache" / "video.mp4").write_bytes(b"remote-build")
            (current_data / "link_cache" / "links.json").write_text("[]", encoding="utf-8")
            (current_data / "cache" / "preview.mp4").write_bytes(b"preview")
            (current_data / "mobile_uploads" / "query.png").write_bytes(b"mobile")
            target_root = root / "target"

            config = {
                "data_root": str(current_root),
                "meta_file": str(current_data / "meta.json"),
            }
            saved_configs = []

            with (
                patch("src.services.storage_service.load_config", return_value=config),
                patch("src.services.storage_service.save_config", side_effect=saved_configs.append),
            ):
                result = storage_service.migrate_app_data_root(str(target_root))

            self.assertTrue(result["migrated"])
            self.assertTrue((target_root / "data" / "remote" / "build_report.json").exists())
            self.assertTrue((target_root / "data" / "remote_build_cache" / "video.mp4").exists())
            self.assertTrue((target_root / "data" / "link_cache" / "links.json").exists())
            self.assertTrue((target_root / "data" / "cache" / "preview.mp4").exists())
            self.assertTrue((target_root / "data" / "mobile_uploads" / "query.png").exists())
            self.assertEqual(saved_configs[0]["data_root"], str(target_root))

    def test_migrate_model_root_copies_tree_and_updates_profiles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            src = root / "src_models"
            dst = root / "dst_models"
            (src / "openai-clip" / "vit-base-patch32").mkdir(parents=True)
            (src / "openai-clip" / "vit-base-patch32" / "clip_visual.onnx").write_bytes(b"onnx")
            config = {
                "schema_version": 2,
                "model_dir": str(src),
                "models": {
                    "active_profile": "p1",
                    "profiles": [
                        {
                            "id": "p1",
                            "provider": "clip_onnx",
                            "runtime": {
                                "model_dir": str(src),
                                "model_variant": "vit-base-patch32",
                                "prefer_gpu": False,
                            },
                        }
                    ],
                },
            }
            saved = []

            with (
                patch("src.services.storage_service.load_config", return_value=dict(config)),
                patch("src.services.storage_service.save_config", side_effect=saved.append),
            ):
                result = storage_service.migrate_model_root(str(dst))

            self.assertTrue(result["migrated"])
            self.assertEqual(result.get("transfer_mode"), "move")
            self.assertFalse(result.get("old_remaining"))
            self.assertTrue((dst / "openai-clip" / "vit-base-patch32" / "clip_visual.onnx").exists())
            self.assertFalse(src.exists())
            self.assertEqual(saved[0]["model_dir"], str(dst))
            self.assertEqual(saved[0]["models"]["profiles"][0]["runtime"]["model_dir"], str(dst))
            self.assertNotIn("pending_cleanup_model_dir", saved[0])

    def test_cleanup_old_model_dir_removes_tree_when_safe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_dir = root / "old_models"
            new_dir = root / "new_models"
            (old_dir / "x").mkdir(parents=True)
            (old_dir / "x" / "f.txt").write_text("ok", encoding="utf-8")
            active_cfg = {
                "schema_version": 2,
                "model_dir": str(new_dir),
                "models": {
                    "active_profile": "p1",
                    "profiles": [
                        {
                            "id": "p1",
                            "provider": "clip_onnx",
                            "runtime": {
                                "model_dir": str(new_dir),
                                "model_variant": "vit-base-patch32",
                                "prefer_gpu": False,
                            },
                        }
                    ],
                },
            }
            with patch("src.services.storage_service.load_config", return_value=dict(active_cfg)):
                result = storage_service.cleanup_old_model_dir(str(old_dir))

            self.assertTrue(result["cleaned"])
            self.assertFalse(old_dir.exists())

    def test_cleanup_old_model_dir_refuses_when_active_inside_pending(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pending = root / "models"
            active_inside = pending / "openai-clip"
            active_inside.mkdir(parents=True)
            cfg = {
                "schema_version": 2,
                "model_dir": str(active_inside),
                "models": {
                    "active_profile": "p1",
                    "profiles": [
                        {
                            "id": "p1",
                            "provider": "clip_onnx",
                            "runtime": {
                                "model_dir": str(active_inside),
                                "model_variant": "vit-base-patch32",
                                "prefer_gpu": False,
                            },
                        }
                    ],
                },
            }
            with patch("src.services.storage_service.load_config", return_value=dict(cfg)):
                with self.assertRaises(ValueError):
                    storage_service.cleanup_old_model_dir(str(pending))

    def test_migrate_app_data_root_same_volume_moves_data_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_root = root / "current"
            current_data = current_root / "data"
            (current_data / "vector").mkdir(parents=True)
            (current_data / "meta.json").write_text('{"libraries": {}}', encoding="utf-8")
            (current_data / "vector" / "sample.npy").write_bytes(b"vector-data")
            (current_root / "logs").mkdir(parents=True)
            (current_root / "logs" / "app.log").write_text("log-data", encoding="utf-8")
            (current_root / "models").mkdir(parents=True)
            (current_root / "models" / "clip.onnx").write_bytes(b"model-data")
            (current_root / "ffmpeg.exe").write_bytes(b"ffmpeg")
            target_root = root / "target"

            config = {
                "data_root": str(current_root),
                "meta_file": str(current_data / "meta.json"),
                "model_dir": str(current_root / "models"),
                "ffmpeg_path": str(current_root / "ffmpeg.exe"),
            }

            with (
                patch("src.services.storage_service.load_config", return_value=config),
                patch("src.services.storage_service.save_config"),
            ):
                result = storage_service.migrate_app_data_root(str(target_root))

            self.assertTrue(result["migrated"])
            self.assertEqual(result.get("transfer_mode"), "move")
            self.assertFalse(result.get("old_remaining"))
            self.assertFalse((current_root / "data").exists())
            self.assertTrue((target_root / "data" / "meta.json").exists())
            self.assertTrue((current_root / "logs" / "app.log").exists())
            self.assertTrue((current_root / "models" / "clip.onnx").exists())
            self.assertTrue((current_root / "ffmpeg.exe").exists())
            self.assertFalse((target_root / "logs" / "app.log").exists())
            self.assertFalse((target_root / "models").exists())
            self.assertFalse((target_root / "ffmpeg.exe").exists())

    def test_migrate_app_data_root_cross_volume_copy_keeps_old_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_root = root / "current"
            current_data = current_root / "data"
            (current_data / "vector").mkdir(parents=True)
            (current_data / "meta.json").write_text('{"libraries": {}}', encoding="utf-8")
            (current_data / "vector" / "sample.npy").write_bytes(b"vector-data")
            target_root = root / "target"
            config = {
                "data_root": str(current_root),
                "meta_file": str(current_data / "meta.json"),
            }
            saved = []

            with (
                patch("src.services.storage_service.load_config", return_value=config),
                patch("src.services.storage_service.save_config", side_effect=saved.append),
                patch("src.services.storage_service._same_volume", return_value=False),
            ):
                result = storage_service.migrate_app_data_root(str(target_root))

            self.assertTrue(result["migrated"])
            self.assertEqual(result.get("transfer_mode"), "copy")
            self.assertTrue(result.get("old_remaining"))
            self.assertTrue((current_root / "data" / "meta.json").exists())
            self.assertTrue((target_root / "data" / "meta.json").exists())
            self.assertEqual(saved[0].get("pending_cleanup_data_root"), str(current_root))

    def test_migrate_app_data_root_accepts_library_db_without_meta_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_root = root / "current"
            profile_base = (
                current_root
                / "data"
                / "model_assets"
                / "openai-clip"
                / "vit-base-patch32"
            )
            profile_base.mkdir(parents=True)
            (profile_base / "library.db").write_bytes(b"sqlite")
            target_root = root / "target"
            config = {
                "schema_version": 2,
                "data_root": str(current_root),
                "meta_file": str(current_root / "data" / "meta.json"),
                "models": {
                    "active_profile": "p1",
                    "profiles": [
                        {
                            "id": "p1",
                            "provider": "clip_onnx",
                            "runtime": {
                                "model_dir": str(root / "models"),
                                "model_variant": "vit-base-patch32",
                                "prefer_gpu": False,
                            },
                        }
                    ],
                },
            }

            with (
                patch("src.services.storage_service.load_config", return_value=config),
                patch("src.services.storage_service.save_config"),
                patch(
                    "src.services.storage_service.get_model_profile_storage_paths",
                    side_effect=lambda config=None: {
                        "meta_file": str(
                            Path(config["data_root"])
                            / "data"
                            / "model_assets"
                            / "openai-clip"
                            / "vit-base-patch32"
                            / "meta.json"
                        ),
                        "base_dir": str(
                            Path(config["data_root"])
                            / "data"
                            / "model_assets"
                            / "openai-clip"
                            / "vit-base-patch32"
                        ),
                    },
                ),
            ):
                result = storage_service.migrate_app_data_root(str(target_root))

            self.assertTrue(result["migrated"])
            self.assertTrue(
                (
                    target_root
                    / "data"
                    / "model_assets"
                    / "openai-clip"
                    / "vit-base-patch32"
                    / "library.db"
                ).exists()
            )

    def test_migrate_app_data_root_rejects_non_empty_target_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_root = root / "current"
            current_data = current_root / "data"
            current_data.mkdir(parents=True)
            (current_data / "meta.json").write_text('{"libraries": {}}', encoding="utf-8")

            target_root = root / "target"
            target_data = target_root / "data"
            target_data.mkdir(parents=True)
            (target_data / "existing.txt").write_text("busy", encoding="utf-8")

            config = {
                "data_root": str(current_root),
                "meta_file": str(current_data / "meta.json"),
            }

            with patch("src.services.storage_service.load_config", return_value=config):
                with self.assertRaises(ValueError):
                    storage_service.migrate_app_data_root(str(target_root))


if __name__ == "__main__":
    unittest.main()
