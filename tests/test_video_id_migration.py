import json
import os
import tempfile
import unittest

import numpy as np

from src.storage.asset_store import save_vector_payload
from src.storage.migration_runner import needs_background_startup_migration, run_startup_migration_quick
from src.storage.video_id_migration import (
    VIDEO_ID_FORMAT_VERSION,
    VIDEO_ID_PENDING_CHECK_PASSED,
    iter_model_asset_storage_roots,
    legacy_video_ids_pending,
    migrate_legacy_video_ids,
    migrate_model_storage_root,
    video_id_migration_completed,
)
from unittest.mock import patch
from src.utils import get_legacy_video_hash, get_video_hash


class VideoIdMigrationTests(unittest.TestCase):
    def test_legacy_and_current_hash_differ_when_mtime_included(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"videoseek-test-content")
            path = handle.name
        try:
            self.assertNotEqual(get_legacy_video_hash(path), get_video_hash(path))
        finally:
            os.remove(path)

    def test_migrate_renames_assets_and_updates_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            base_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
            vector_dir = os.path.join(base_dir, "vector")
            index_dir = os.path.join(base_dir, "index")
            library_root = os.path.join(tmp, "library")
            os.makedirs(vector_dir, exist_ok=True)
            os.makedirs(index_dir, exist_ok=True)
            os.makedirs(library_root, exist_ok=True)

            video_path = os.path.join(library_root, "clip.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"x" * 2048)

            legacy_vid = get_legacy_video_hash(video_path)
            new_vid = get_video_hash(video_path)
            vectors = np.zeros((3, 512), dtype=np.float32)
            timestamps = [0.0, 1.0, 2.0]
            save_vector_payload(vectors, timestamps, os.path.join(vector_dir, f"{legacy_vid}_vectors.npy"))

            meta = {
                "schema_version": 2,
                "libraries": {
                    library_root: {
                        "files": {
                            "clip.mp4": {
                                "vid": legacy_vid,
                                "mod_time": os.path.getmtime(video_path),
                                "asset_state": "ready",
                            }
                        }
                    }
                },
            }
            meta_file = os.path.join(base_dir, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)

            config = {
                "data_root": tmp,
                "meta_file": meta_file,
                "vector_dir": vector_dir,
                "index_dir": index_dir,
            }
            roots = list(iter_model_asset_storage_roots(config))
            self.assertEqual(len(roots), 1)

            stats = migrate_model_storage_root(roots[0])
            self.assertEqual(stats["migrated"], 1)
            self.assertTrue(os.path.isfile(os.path.join(vector_dir, f"{new_vid}_vectors.npy")))
            self.assertFalse(os.path.isfile(os.path.join(vector_dir, f"{legacy_vid}_vectors.npy")))

            with open(meta_file, "r", encoding="utf-8") as handle:
                migrated_meta = json.load(handle)
            entry = migrated_meta["libraries"][library_root]["files"]["clip.mp4"]
            self.assertEqual(entry["vid"], new_vid)
            self.assertNotEqual(migrated_meta.get("global_index_state"), "stale")

    def test_migration_marks_state_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            config = {"data_root": tmp}
            self.assertFalse(video_id_migration_completed(config))
            result = migrate_legacy_video_ids(config=config)
            self.assertEqual(result["video_id_format"], VIDEO_ID_FORMAT_VERSION)
            self.assertTrue(video_id_migration_completed(config))

    def test_pending_when_meta_has_new_vid_but_vectors_use_legacy_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            base_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
            vector_dir = os.path.join(base_dir, "vector")
            library_root = os.path.join(tmp, "library")
            os.makedirs(vector_dir, exist_ok=True)
            os.makedirs(library_root, exist_ok=True)

            video_path = os.path.join(library_root, "clip.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"x" * 2048)

            legacy_vid = get_legacy_video_hash(video_path)
            new_vid = get_video_hash(video_path)
            save_vector_payload(
                np.zeros((2, 512), dtype=np.float32),
                [0.0, 1.0],
                os.path.join(vector_dir, f"{legacy_vid}_vectors.npy"),
            )

            meta = {
                "libraries": {
                    library_root: {
                        "files": {
                            "clip.mp4": {"vid": new_vid, "mod_time": os.path.getmtime(video_path), "asset_state": "ready"},
                        }
                    }
                }
            }
            meta_file = os.path.join(base_dir, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)

            state_file = os.path.join(data_dir, "migration_state.json")
            with open(state_file, "w", encoding="utf-8") as handle:
                json.dump({"video_id_format": 2, "completed": True}, handle)

            config = {"data_root": tmp}
            self.assertTrue(legacy_video_ids_pending(config))
            stats = migrate_model_storage_root(
                {
                    "meta_file": meta_file,
                    "vector_dir": vector_dir,
                    "index_dir": os.path.join(base_dir, "index"),
                    "base_dir": base_dir,
                    "label": "test",
                }
            )
            self.assertEqual(stats["migrated"], 1)
            self.assertTrue(os.path.isfile(os.path.join(vector_dir, f"{new_vid}_vectors.npy")))

    def test_completed_flag_ignored_while_legacy_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            base_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
            vector_dir = os.path.join(base_dir, "vector")
            library_root = os.path.join(tmp, "library")
            os.makedirs(vector_dir, exist_ok=True)
            os.makedirs(library_root, exist_ok=True)

            video_path = os.path.join(library_root, "clip.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"x" * 2048)

            legacy_vid = get_legacy_video_hash(video_path)
            new_vid = get_video_hash(video_path)
            save_vector_payload(
                np.zeros((2, 512), dtype=np.float32),
                [0.0, 1.0],
                os.path.join(vector_dir, f"{legacy_vid}_vectors.npy"),
            )

            meta = {
                "libraries": {
                    library_root: {
                        "files": {
                            "clip.mp4": {"vid": legacy_vid, "mod_time": os.path.getmtime(video_path), "asset_state": "ready"},
                        }
                    }
                }
            }
            meta_file = os.path.join(base_dir, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)

            state_file = os.path.join(data_dir, "migration_state.json")
            with open(state_file, "w", encoding="utf-8") as handle:
                json.dump({"video_id_format": 2, "completed": True}, handle)

            config = {"data_root": tmp}
            self.assertTrue(legacy_video_ids_pending(config))
            self.assertFalse(video_id_migration_completed(config))
            result = migrate_legacy_video_ids(config=config)
            self.assertEqual(result["migrated_video_ids"], 1)
            self.assertFalse(result.get("pending_legacy"))
            self.assertTrue(video_id_migration_completed(config))

    def test_trusted_fast_check_skips_per_file_hash_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            base_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
            vector_dir = os.path.join(base_dir, "vector")
            library_root = os.path.join(tmp, "library")
            os.makedirs(vector_dir, exist_ok=True)
            os.makedirs(library_root, exist_ok=True)

            video_path = os.path.join(library_root, "clip.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"x" * 2048)

            new_vid = get_video_hash(video_path)
            save_vector_payload(
                np.zeros((2, 512), dtype=np.float32),
                [0.0, 1.0],
                os.path.join(vector_dir, f"{new_vid}_vectors.npy"),
            )

            meta = {
                "libraries": {
                    library_root: {
                        "files": {
                            "clip.mp4": {
                                "vid": new_vid,
                                "mod_time": os.path.getmtime(video_path),
                                "asset_state": "ready",
                            }
                        }
                    }
                }
            }
            meta_file = os.path.join(base_dir, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)

            state_file = os.path.join(data_dir, "migration_state.json")
            with open(state_file, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "video_id_format": VIDEO_ID_FORMAT_VERSION,
                        "video_id_pending_check": VIDEO_ID_PENDING_CHECK_PASSED,
                    },
                    handle,
                )

            config = {"data_root": tmp}
            with patch("src.storage.video_id_migration.get_video_hash") as mock_hash:
                self.assertFalse(legacy_video_ids_pending(config))
                mock_hash.assert_not_called()

    def test_lance_only_without_npy_skips_video_hash_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            base_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
            library_root = os.path.join(tmp, "library")
            os.makedirs(base_dir, exist_ok=True)
            os.makedirs(library_root, exist_ok=True)
            video_path = os.path.join(library_root, "clip.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"x" * 2048)

            meta = {
                "schema_version": 2,
                "libraries": {
                    library_root: {
                        "files": {
                            "clip.mp4": {
                                "vid": get_video_hash(video_path),
                                "mod_time": os.path.getmtime(video_path),
                                "asset_state": "ready",
                            }
                        }
                    }
                },
            }
            meta_file = os.path.join(base_dir, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)

            config = {"data_root": tmp, "schema_version": 2}
            with patch("src.storage.video_id_migration.get_video_hash") as mock_hash:
                mock_hash.side_effect = AssertionError("Lance-only startup should not hash videos")
                result = migrate_legacy_video_ids(config=config)
                self.assertFalse(result.get("migrated"))
                self.assertFalse(legacy_video_ids_pending(config))
                self.assertTrue(video_id_migration_completed(config))

    def _write_dummy_model_files(self, model_root):
        model_dir = os.path.join(model_root, "openai-clip", "vit-base-patch32")
        os.makedirs(model_dir, exist_ok=True)
        for name in ("clip_visual.onnx", "clip_text.onnx", "bpe_simple_vocab_16e6.txt.gz"):
            path = os.path.join(model_dir, name)
            with open(path, "wb") as handle:
                handle.write(b"0")

    def test_quick_startup_skips_background_when_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            base_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
            vector_dir = os.path.join(base_dir, "vector")
            index_dir = os.path.join(base_dir, "index")
            global_dir = os.path.join(base_dir, "global")
            remote_dir = os.path.join(base_dir, "remote")
            model_dir = os.path.join(tmp, "models")
            library_root = os.path.join(tmp, "library")
            os.makedirs(vector_dir, exist_ok=True)
            os.makedirs(index_dir, exist_ok=True)
            os.makedirs(global_dir, exist_ok=True)
            os.makedirs(remote_dir, exist_ok=True)
            os.makedirs(library_root, exist_ok=True)
            self._write_dummy_model_files(model_dir)

            video_path = os.path.join(library_root, "clip.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"x" * 2048)

            new_vid = get_video_hash(video_path)
            save_vector_payload(
                np.zeros((2, 512), dtype=np.float32),
                [0.0, 1.0],
                os.path.join(vector_dir, f"{new_vid}_vectors.npy"),
            )

            meta = {
                "schema_version": 2,
                "libraries": {
                    library_root: {
                        "files": {
                            "clip.mp4": {
                                "vid": new_vid,
                                "mod_time": os.path.getmtime(video_path),
                                "asset_state": "ready",
                            }
                        }
                    }
                },
            }
            meta_file = os.path.join(base_dir, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)

            state_file = os.path.join(data_dir, "migration_state.json")
            with open(state_file, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "completed": True,
                        "schema_version": 2,
                        "video_id_format": VIDEO_ID_FORMAT_VERSION,
                        "video_id_pending_check": VIDEO_ID_PENDING_CHECK_PASSED,
                    },
                    handle,
                )

            config = {
                "data_root": tmp,
                "schema_version": 2,
                "models": {
                    "active_profile": "clip_onnx_default",
                    "profiles": [
                        {
                            "id": "clip_onnx_default",
                            "provider": "clip_onnx",
                            "runtime": {"model_dir": model_dir, "model_variant": "vit-base-patch32"},
                            "files": {
                                "visual_model": "clip_visual.onnx",
                                "text_model": "clip_text.onnx",
                                "tokenizer_vocab": "bpe_simple_vocab_16e6.txt.gz",
                            },
                        }
                    ],
                },
            }
            with patch("src.storage.migration_runner.load_config", return_value=config):
                with patch("src.storage.migration_runner.needs_search_index_schema_migration", return_value=False):
                    self.assertFalse(needs_background_startup_migration())
                    quick = run_startup_migration_quick()
            self.assertFalse(quick.get("needs_background"))


if __name__ == "__main__":
    unittest.main()
