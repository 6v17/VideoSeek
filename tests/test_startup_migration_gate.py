"""Startup migration gating — schema completion must not require installed model weights."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.modules.setdefault("cv2", object())
sys.modules.setdefault("numpy", object())
sys.modules.setdefault("faiss", object())

from src.storage import migration_runner as migration_runner_module


class StartupMigrationGateTests(unittest.TestCase):
    def test_already_migrated_true_without_onnx_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = os.path.join(tmp, "profile")
            data_dir = os.path.join(data_root, "data")
            model_assets = os.path.join(
                data_dir, "model_assets", "openai-clip", "vit-base-patch32"
            )
            for path in (
                os.path.join(model_assets, "vector"),
                os.path.join(model_assets, "index"),
                os.path.join(model_assets, "global"),
                os.path.join(model_assets, "remote"),
                os.path.join(data_root, "models", "openai-clip", "vit-base-patch32"),
            ):
                os.makedirs(path, exist_ok=True)
            meta_file = os.path.join(model_assets, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump({"libraries": {}, "schema_version": 2}, handle)

            state_file = os.path.join(data_dir, "migration_state.json")
            with open(state_file, "w", encoding="utf-8") as handle:
                json.dump({"completed": True, "schema_version": 2}, handle)

            config = {
                "schema_version": 2,
                "data_root": data_root,
                "model_dir": os.path.join(data_root, "models"),
                "models": {
                    "active_profile": "clip_onnx_default",
                    "profiles": [
                        {
                            "id": "clip_onnx_default",
                            "provider": "clip_onnx",
                            "runtime": {
                                "model_dir": os.path.join(data_root, "models"),
                                "model_variant": "vit-base-patch32",
                            },
                            "files": {
                                "visual": "clip_visual.onnx",
                                "text": "clip_text.onnx",
                            },
                        }
                    ],
                },
            }
            meta = {"libraries": {}, "schema_version": 2}

            with (
                patch.object(
                    migration_runner_module,
                    "get_local_model_asset_dirs",
                    return_value={
                        "base_dir": model_assets,
                        "vector_dir": os.path.join(model_assets, "vector"),
                        "index_dir": os.path.join(model_assets, "index"),
                        "meta_file": meta_file,
                    },
                ),
                patch.object(
                    migration_runner_module,
                    "get_global_model_asset_paths",
                    return_value={"global_dir": os.path.join(model_assets, "global")},
                ),
                patch.object(
                    migration_runner_module,
                    "_migration_state_file",
                    return_value=state_file,
                ),
            ):
                self.assertTrue(migration_runner_module._already_migrated(config, meta))

    def test_create_backup_skipped_for_empty_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {"data_root": tmp}
            self.assertFalse(migration_runner_module._data_dir_has_user_payload(config))
            self.assertEqual(migration_runner_module._create_backup(config), "")

    def test_create_backup_runs_when_data_dir_has_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            meta_file = os.path.join(data_dir, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump({"libraries": {}}, handle)
            config = {"data_root": tmp}
            self.assertTrue(migration_runner_module._data_dir_has_user_payload(config))
            backup_dir = migration_runner_module._create_backup(config)
            self.assertTrue(backup_dir)
            self.assertTrue(os.path.isdir(backup_dir))
            self.assertTrue(os.path.exists(os.path.join(backup_dir, "meta.json")))


    def test_needs_background_true_when_lance_migration_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = os.path.join(tmp, "profile")
            data_dir = os.path.join(data_root, "data")
            model_assets = os.path.join(
                data_dir, "model_assets", "openai-clip", "vit-base-patch32"
            )
            vector_dir = os.path.join(model_assets, "vector")
            for path in (
                vector_dir,
                os.path.join(model_assets, "index"),
                os.path.join(model_assets, "global"),
            ):
                os.makedirs(path, exist_ok=True)
            with open(os.path.join(vector_dir, "abc_vectors.npy"), "wb") as handle:
                handle.write(b"placeholder")
            meta_file = os.path.join(model_assets, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump({"libraries": {}, "schema_version": 2}, handle)
            state_file = os.path.join(data_dir, "migration_state.json")
            with open(state_file, "w", encoding="utf-8") as handle:
                json.dump({"completed": True, "schema_version": 2}, handle)
            config = {
                "schema_version": 2,
                "data_root": data_root,
                "model_dir": os.path.join(data_root, "models"),
                "models": {
                    "active_profile": "clip_onnx_default",
                    "profiles": [
                        {
                            "id": "clip_onnx_default",
                            "provider": "clip_onnx",
                            "runtime": {
                                "model_dir": os.path.join(data_root, "models"),
                                "model_variant": "vit-base-patch32",
                            },
                            "files": {
                                "visual": "clip_visual.onnx",
                                "text": "clip_text.onnx",
                            },
                        }
                    ],
                },
            }
            with (
                patch.object(migration_runner_module, "load_config", return_value=config),
                patch.object(migration_runner_module, "_trust_fast_video_id_check", return_value=True),
                patch.object(migration_runner_module, "_legacy_video_ids_pending_fast", return_value=False),
            ):
                self.assertTrue(migration_runner_module.needs_background_startup_migration(config))


if __name__ == "__main__":
    unittest.main()
