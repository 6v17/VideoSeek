"""Startup Lance migration detection and legacy cleanup helpers."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.modules.setdefault("cv2", object())

from src.core.faiss_index import save_vectors
from src.storage import lance_migration_runner as lance_migration_module
from src.storage.asset_store import save_metadata


class LanceMigrationRunnerTests(unittest.TestCase):
    def _write_npy_vector(self, profile_dir: str, video_id: str) -> None:
        vector_dir = os.path.join(profile_dir, "vector")
        os.makedirs(vector_dir, exist_ok=True)
        vector_file = os.path.join(vector_dir, f"{video_id}_vectors.npy")
        vectors = np.random.randn(4, 8).astype(np.float32)
        timestamps = np.asarray([0.0, 1.0, 2.0, 3.0], dtype=np.float32)
        save_vectors(vectors, timestamps, vector_file)
        save_metadata(
            {
                "libraries": {
                    profile_dir: {
                        "files": {
                            "clip.mp4": {"vid": video_id, "asset_state": "ready"},
                        }
                    }
                }
            },
            os.path.join(profile_dir, "meta.json"),
        )

    def test_needs_lance_startup_migration_when_npy_without_lance(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = os.path.join(tmp, "openai-clip", "vit-base-patch32")
            self._write_npy_vector(profile_dir, "vid001")
            config = {"data_root": tmp, "vector_search_backend": "auto"}
            roots = [{"label": "clip", "base_dir": profile_dir}]
            with patch.object(
                lance_migration_module,
                "iter_model_asset_storage_roots",
                return_value=roots,
            ):
                self.assertTrue(lance_migration_module.needs_lance_startup_migration(config))

    def test_needs_lance_startup_migration_for_legacy_cleanup_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = os.path.join(tmp, "openai-clip", "vit-base-patch32")
            self._write_npy_vector(profile_dir, "vid001")
            config = {"data_root": tmp, "vector_search_backend": "auto"}
            roots = [{"label": "clip", "base_dir": profile_dir}]
            with (
                patch.object(
                    lance_migration_module,
                    "iter_model_asset_storage_roots",
                    return_value=roots,
                ),
                patch.object(
                    lance_migration_module,
                    "lance_search_is_ready",
                    return_value=True,
                ),
                patch.object(
                    lance_migration_module,
                    "_read_lance_migration_state",
                    return_value={},
                ),
            ):
                self.assertTrue(lance_migration_module.needs_lance_startup_migration(config))

    def test_needs_lance_startup_migration_skips_npy_after_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = os.path.join(tmp, "openai-clip", "vit-base-patch32")
            self._write_npy_vector(profile_dir, "vid001")
            config = {"data_root": tmp, "vector_search_backend": "auto"}
            roots = [{"label": "clip", "base_dir": profile_dir}]
            with (
                patch.object(
                    lance_migration_module,
                    "iter_model_asset_storage_roots",
                    return_value=roots,
                ),
                patch.object(
                    lance_migration_module,
                    "lance_search_is_ready",
                    return_value=True,
                ),
                patch.object(
                    lance_migration_module,
                    "_read_lance_migration_state",
                    return_value={"completed": True},
                ),
            ):
                self.assertFalse(lance_migration_module.needs_lance_startup_migration(config))

    def test_needs_lance_startup_migration_retries_when_previous_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = os.path.join(tmp, "openai-clip", "vit-base-patch32")
            self._write_npy_vector(profile_dir, "vid001")
            config = {"data_root": tmp, "vector_search_backend": "auto"}
            roots = [{"label": "clip", "base_dir": profile_dir}]
            with (
                patch.object(
                    lance_migration_module,
                    "iter_model_asset_storage_roots",
                    return_value=roots,
                ),
                patch.object(
                    lance_migration_module,
                    "lance_search_is_ready",
                    return_value=True,
                ),
                patch.object(
                    lance_migration_module,
                    "_read_lance_migration_state",
                    return_value={"completed": True, "videos_failed": 2},
                ),
            ):
                self.assertFalse(lance_migration_module.is_lance_migration_completed(config))
                self.assertTrue(lance_migration_module.needs_lance_startup_migration(config))

    def test_run_lance_startup_migration_does_not_complete_when_import_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = os.path.join(tmp, "openai-clip", "vit-base-patch32")
            self._write_npy_vector(profile_dir, "vid001")
            config = {"data_root": tmp, "vector_search_backend": "auto"}
            roots = [{"label": "clip", "base_dir": profile_dir}]
            written = {}

            def _capture_state(_config, payload):
                written.clear()
                written.update(payload)

            with (
                patch.object(
                    lance_migration_module,
                    "iter_model_asset_storage_roots",
                    return_value=roots,
                ),
                patch.object(
                    lance_migration_module,
                    "lance_search_is_ready",
                    side_effect=[False, True],
                ),
                patch.object(
                    lance_migration_module,
                    "import_npy_to_lance",
                    return_value={
                        "videos_imported": 1,
                        "videos_failed": 1,
                        "errors": ["vid_bad.npy: boom"],
                    },
                ),
                patch.object(
                    lance_migration_module,
                    "cleanup_legacy_vector_paths",
                    return_value=0,
                ),
                patch.object(
                    lance_migration_module,
                    "_mark_profile_search_index_ready",
                ),
                patch.object(
                    lance_migration_module,
                    "_write_lance_migration_state",
                    side_effect=_capture_state,
                ),
                patch.object(
                    lance_migration_module,
                    "_read_lance_migration_state",
                    return_value={},
                ),
            ):
                result = lance_migration_module.run_lance_startup_migration(config)

            self.assertEqual(int(result.get("lance_videos_failed", 0) or 0), 1)
            self.assertFalse(written.get("completed"))
            self.assertEqual(int(written.get("videos_failed", 0) or 0), 1)

    def test_collect_and_cleanup_legacy_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = os.path.join(tmp, "profile")
            self._write_npy_vector(profile_dir, "vid001")
            paths = lance_migration_module.collect_legacy_vector_paths(profile_dir)
            self.assertEqual(len(paths), 1)
            removed = lance_migration_module.cleanup_legacy_vector_paths(paths)
            self.assertEqual(removed, 1)
            self.assertFalse(os.path.exists(paths[0]))

    def test_cleanup_safe_legacy_vector_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = os.path.join(tmp, "openai-clip", "vit-base-patch32")
            self._write_npy_vector(profile_dir, "vid001")
            npy_path = os.path.join(profile_dir, "vector", "vid001_vectors.npy")
            self.assertTrue(os.path.isfile(npy_path))
            config = {"data_root": tmp}

            with (
                patch(
                    "src.storage.config_store.get_local_model_asset_dirs",
                    return_value={"base_dir": profile_dir},
                ),
                patch.object(
                    lance_migration_module,
                    "lance_search_is_ready",
                    return_value=False,
                ),
            ):
                blocked = lance_migration_module.cleanup_safe_legacy_vector_sidecars(config=config)
            self.assertFalse(blocked["ready"])
            self.assertEqual(blocked["removed"], 0)
            self.assertEqual(blocked["message_key"], "library_vectors_legacy_cleanup_not_ready")
            self.assertTrue(os.path.isfile(npy_path))

            with (
                patch(
                    "src.storage.config_store.get_local_model_asset_dirs",
                    return_value={"base_dir": profile_dir},
                ),
                patch.object(
                    lance_migration_module,
                    "lance_search_is_ready",
                    return_value=True,
                ),
            ):
                cleaned = lance_migration_module.cleanup_safe_legacy_vector_sidecars(config=config)
            self.assertTrue(cleaned["ready"])
            self.assertEqual(cleaned["removed"], 1)
            self.assertGreater(cleaned["bytes_freed_estimate"], 0)
            self.assertEqual(cleaned["message_key"], "library_vectors_legacy_cleanup_done")
            self.assertFalse(os.path.isfile(npy_path))

            with (
                patch(
                    "src.storage.config_store.get_local_model_asset_dirs",
                    return_value={"base_dir": profile_dir},
                ),
                patch.object(
                    lance_migration_module,
                    "lance_search_is_ready",
                    return_value=True,
                ),
            ):
                empty = lance_migration_module.cleanup_safe_legacy_vector_sidecars(config=config)
            self.assertTrue(empty["ready"])
            self.assertEqual(empty["removed"], 0)
            self.assertEqual(empty["message_key"], "library_vectors_legacy_cleanup_empty")

    def test_run_lance_startup_migration_skips_npy_when_lance_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = os.path.join(tmp, "openai-clip", "vit-base-patch32")
            self._write_npy_vector(profile_dir, "vid001")
            config = {"data_root": tmp, "vector_search_backend": "auto"}
            roots = [{"label": "clip", "base_dir": profile_dir}]
            with (
                patch.object(
                    lance_migration_module,
                    "iter_model_asset_storage_roots",
                    return_value=roots,
                ),
                patch.object(
                    lance_migration_module,
                    "lance_search_is_ready",
                    return_value=True,
                ),
                patch.object(
                    lance_migration_module,
                    "import_npy_to_lance",
                ) as import_mock,
                patch.object(
                    lance_migration_module,
                    "cleanup_legacy_vector_paths",
                    return_value=0,
                ),
                patch.object(
                    lance_migration_module,
                    "_mark_profile_search_index_ready",
                ),
                patch.object(
                    lance_migration_module,
                    "_write_lance_migration_state",
                ),
            ):
                result = lance_migration_module.run_lance_startup_migration(config)
            import_mock.assert_not_called()
            self.assertFalse(result.get("upgraded"))

    def test_run_lance_startup_migration_writes_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            profile_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
            self._write_npy_vector(profile_dir, "vid001")
            state_file = os.path.join(data_dir, "migration_state.json")
            config = {"data_root": tmp, "vector_search_backend": "auto"}
            roots = [{"label": "clip", "base_dir": profile_dir}]

            try:
                import lancedb  # noqa: F401
            except ImportError:
                self.skipTest("lancedb not installed")

            with (
                patch.object(
                    lance_migration_module,
                    "iter_model_asset_storage_roots",
                    return_value=roots,
                ),
                patch.object(
                    lance_migration_module,
                    "_migration_state_file",
                    return_value=state_file,
                ),
            ):
                result = lance_migration_module.run_lance_startup_migration(config)
            self.assertTrue(result.get("upgraded"))
            self.assertGreaterEqual(int(result.get("lance_videos_imported", 0) or 0), 1)
            with open(state_file, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            self.assertTrue(state.get("lance_migration", {}).get("completed"))


if __name__ == "__main__":
    unittest.main()
