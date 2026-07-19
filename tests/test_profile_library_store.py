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


if __name__ == "__main__":
    unittest.main()
