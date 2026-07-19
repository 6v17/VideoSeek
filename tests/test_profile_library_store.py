import json
import os
import tempfile
import unittest


class ProfileLibraryStoreTests(unittest.TestCase):
    def test_save_load_meta_roundtrip(self):
        from src.storage.profile_library_store import (
            get_library_db_path,
            load_profile_meta,
            save_profile_meta,
        )

        with tempfile.TemporaryDirectory() as tmp:
            profile = os.path.join(tmp, "profile")
            os.makedirs(profile, exist_ok=True)
            meta = {
                "schema_version": 2,
                "libraries": {
                    os.path.normpath(tmp): {
                        "files": {
                            "a.mp4": {
                                "vid": "v1",
                                "mod_time": 1.5,
                                "asset_state": "ready",
                            },
                            "b.mp4": {
                                "vid": "v2",
                                "mod_time": 2.5,
                                "asset_state": "sync_failed",
                                "sync_failure_reason": "no_frames",
                            },
                        },
                        "last_scan": "",
                        "index_state": "partial",
                        "discover_cache": {"rel_paths": ["a.mp4"]},
                    }
                },
            }
            save_profile_meta(profile, meta)
            self.assertTrue(os.path.isfile(get_library_db_path(profile)))
            loaded = load_profile_meta(profile)
            lib_key = next(iter(loaded["libraries"]))
            files = loaded["libraries"][lib_key]["files"]
            self.assertEqual(files["a.mp4"]["vid"], "v1")
            self.assertEqual(files["b.mp4"]["sync_failure_reason"], "no_frames")
            self.assertEqual(loaded["libraries"][lib_key]["index_state"], "partial")
            self.assertEqual(loaded["schema_version"], 2)
            self.assertEqual(loaded["libraries"][lib_key]["discover_cache"]["rel_paths"], ["a.mp4"])

    def test_migrate_meta_and_import_state_json(self):
        from src.storage.asset_store import load_metadata
        from src.storage.lance_store import (
            get_dialogue_index_state,
            get_stored_chunk_config,
            set_dialogue_index_state,
            set_stored_chunk_config,
        )
        from src.storage.profile_library_store import get_library_db_path

        with tempfile.TemporaryDirectory() as tmp:
            profile = os.path.join(tmp, "profile")
            lance_dir = os.path.join(profile, "lance")
            os.makedirs(lance_dir, exist_ok=True)
            meta_file = os.path.join(profile, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "libraries": {
                            tmp: {
                                "files": {
                                    "ep.mp4": {"vid": "vid001", "asset_state": "ready", "mod_time": 9.0}
                                },
                                "index_state": "ready",
                            }
                        }
                    },
                    handle,
                )
            with open(os.path.join(lance_dir, "import_state.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "storage_version": 1,
                        "videos_total": 1,
                        "videos": {
                            "vid001": {
                                "chunk_config": {"algorithm_version": 7},
                                "dialogue_index_state": "ready",
                                "dialogue_segment_rows": 3,
                            }
                        },
                    },
                    handle,
                )

            loaded = load_metadata(meta_file)
            self.assertTrue(os.path.isfile(get_library_db_path(profile)))
            lib = next(iter(loaded["libraries"].values()))
            self.assertEqual(lib["files"]["ep.mp4"]["vid"], "vid001")
            self.assertEqual(get_stored_chunk_config(profile, "vid001")["algorithm_version"], 7)
            self.assertEqual(get_dialogue_index_state(profile, "vid001"), "ready")

            set_stored_chunk_config(profile, "vid001", {"algorithm_version": 8})
            set_dialogue_index_state(
                profile,
                "vid001",
                "failed",
                extras={"dialogue_error": "boom", "dialogue_segment_rows": 0},
            )
            self.assertEqual(get_stored_chunk_config(profile, "vid001")["algorithm_version"], 8)
            self.assertEqual(get_dialogue_index_state(profile, "vid001"), "failed")

    def test_migrate_meta_file_does_not_wipe_existing_library_db(self):
        from src.storage.migration_runner import _migrate_meta_file
        from src.storage.profile_library_store import load_profile_meta, save_profile_meta

        with tempfile.TemporaryDirectory() as tmp:
            data_root = os.path.join(tmp, "root")
            profile = os.path.join(
                data_root, "data", "model_assets", "openai-clip", "vit-base-patch32"
            )
            os.makedirs(profile, exist_ok=True)
            lib_path = os.path.normpath(os.path.join(tmp, "videos"))
            os.makedirs(lib_path, exist_ok=True)
            save_profile_meta(
                profile,
                {
                    "schema_version": 2,
                    "libraries": {
                        lib_path: {
                            "files": {
                                "a.mp4": {"vid": "keep-me", "asset_state": "ready", "mod_time": 1.0}
                            },
                            "index_state": "ready",
                        }
                    },
                },
            )
            self.assertFalse(os.path.exists(os.path.join(profile, "meta.json")))
            self.assertTrue(os.path.isfile(os.path.join(profile, "library.db")))

            config = {
                "schema_version": 2,
                "data_root": data_root,
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
                        }
                    ],
                },
            }
            result = _migrate_meta_file(config)
            self.assertEqual(result, 0)
            loaded = load_profile_meta(profile)
            self.assertIn(lib_path, loaded["libraries"])
            self.assertEqual(
                loaded["libraries"][lib_path]["files"]["a.mp4"]["vid"],
                "keep-me",
            )


if __name__ == "__main__":
    unittest.main()
