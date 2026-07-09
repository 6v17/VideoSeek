import os
import tempfile
import unittest
from unittest.mock import patch

from src.services.search_index_schema import (
    LIBRARY_SEARCH_INDEX_STATUS_NEEDS_UPGRADE,
    LIBRARY_SEARCH_INDEX_STATUS_NOT_APPLICABLE,
    LIBRARY_SEARCH_INDEX_STATUS_READY,
    LIBRARY_SEARCH_INDEX_STATUS_STALE,
    SEARCH_INDEX_SCHEMA_V1,
    SEARCH_INDEX_SCHEMA_V2,
    TARGET_SEARCH_INDEX_SCHEMA_VERSION,
    clear_library_search_index,
    garbage_collect_orphan_library_indexes,
    get_library_index_paths,
    get_library_search_index_status,
    get_search_index_schema_version,
    library_index_key,
    needs_search_index_upgrade,
    prune_legacy_search_index_artifacts,
)


class SearchIndexSchemaTests(unittest.TestCase):
    def test_library_index_key_is_stable(self):
        with tempfile.TemporaryDirectory() as lib_a:
            key_a = library_index_key(lib_a)
            key_b = library_index_key(os.path.join(lib_a, "."))
            self.assertEqual(key_a, key_b)
            self.assertEqual(len(key_a), 16)

    def test_needs_upgrade_when_schema_missing(self):
        meta = {"libraries": {}}
        self.assertFalse(needs_search_index_upgrade(meta))

    def test_needs_upgrade_when_library_index_missing(self):
        with tempfile.TemporaryDirectory() as lib_root:
            meta = {
                "search_index_schema_version": SEARCH_INDEX_SCHEMA_V2,
                "libraries": {
                    lib_root: {
                        "files": {
                            "clip.mp4": {"asset_state": "ready", "vid": "abc123"},
                        }
                    }
                },
            }
            self.assertFalse(needs_search_index_upgrade(meta))

    def test_needs_upgrade_skips_marked_ready_libraries_without_scanning_files(self):
        with tempfile.TemporaryDirectory() as lib_root:
            paths = get_library_index_paths(lib_root)
            os.makedirs(paths["library_dir"], exist_ok=True)
            open(paths["frame_index_file"], "wb").close()
            open(paths["frame_vector_file"], "wb").close()
            meta = {
                "search_index_schema_version": SEARCH_INDEX_SCHEMA_V2,
                "libraries": {
                    lib_root: {
                        "search_index_schema_version": SEARCH_INDEX_SCHEMA_V2,
                        "files": {
                            "clip.mp4": {"asset_state": "ready", "vid": "abc123"},
                        },
                    }
                },
            }
            with patch(
                "src.services.search_index_schema.library_has_ready_videos",
                side_effect=AssertionError("should not scan files for marked-ready library"),
            ):
                self.assertFalse(needs_search_index_upgrade(meta))

    def test_schema_version_defaults_to_v1(self):
        self.assertEqual(get_search_index_schema_version({}), SEARCH_INDEX_SCHEMA_V1)
        self.assertEqual(TARGET_SEARCH_INDEX_SCHEMA_VERSION, SEARCH_INDEX_SCHEMA_V2)

    def test_meta_schema_version_does_not_count_as_search_index_upgrade(self):
        meta = {
            "schema_version": SEARCH_INDEX_SCHEMA_V2,
            "libraries": {
                "/tmp/lib": {
                    "files": {"clip.mp4": {"asset_state": "ready", "vid": "abc123"}},
                }
            },
        }
        self.assertFalse(needs_search_index_upgrade(meta))
        self.assertEqual(get_search_index_schema_version(meta), SEARCH_INDEX_SCHEMA_V1)

    def test_library_index_paths_layout(self):
        with tempfile.TemporaryDirectory() as lib_root:
            paths = get_library_index_paths(lib_root)
            self.assertIn("library_indexes", paths["library_dir"])
            self.assertTrue(paths["frame_index_file"].endswith("frame_index.faiss"))

    def test_clear_library_search_index_removes_files(self):
        with tempfile.TemporaryDirectory() as lib_root:
            with patch(
                "src.storage.config_store.get_global_model_asset_paths",
                return_value={"global_dir": lib_root},
            ):
                paths = get_library_index_paths(lib_root)
                os.makedirs(paths["library_dir"], exist_ok=True)
                open(paths["frame_index_file"], "wb").close()
                open(paths["frame_vector_file"], "wb").close()
                clear_library_search_index(lib_root)
                self.assertFalse(os.path.exists(paths["frame_index_file"]))
                self.assertFalse(os.path.isdir(paths["library_dir"]))

    def test_garbage_collect_orphan_library_indexes(self):
        with tempfile.TemporaryDirectory() as asset_root:
            with patch(
                "src.storage.config_store.get_global_model_asset_paths",
                return_value={"global_dir": asset_root},
            ):
                lib_root = os.path.join(asset_root, "lib")
                meta = {
                    "libraries": {
                        lib_root: {
                            "files": {"clip.mp4": {"asset_state": "ready", "vid": "abc123"}},
                        }
                    }
                }
                valid_dir = get_library_index_paths(lib_root)["library_dir"]
                orphan_dir = os.path.join(asset_root, "library_indexes", "orphan1234567890")
                os.makedirs(valid_dir, exist_ok=True)
                os.makedirs(orphan_dir, exist_ok=True)
                removed = garbage_collect_orphan_library_indexes(meta)
                self.assertEqual(removed, 1)
                self.assertTrue(os.path.isdir(valid_dir))
                self.assertFalse(os.path.exists(orphan_dir))

    @patch("src.storage.lance_search_index.lance_search_is_ready", return_value=True)
    @patch("src.storage.video_id_migration.legacy_npy_vectors_present", return_value=False)
    def test_prune_legacy_search_index_artifacts(self, _mock_npy, _mock_lance):
        with tempfile.TemporaryDirectory() as asset_root:
            index_dir = os.path.join(asset_root, "index")
            global_dir = os.path.join(asset_root, "global")
            os.makedirs(index_dir, exist_ok=True)
            os.makedirs(global_dir, exist_ok=True)
            faiss_file = os.path.join(index_dir, "abc_index.faiss")
            open(faiss_file, "wb").close()
            open(os.path.join(global_dir, "cross_video_index.faiss"), "wb").close()
            library_root = os.path.join(global_dir, "library_indexes")
            os.makedirs(library_root, exist_ok=True)
            meta = {"libraries": {}}
            with patch(
                "src.storage.config_store.get_local_model_asset_dirs",
                return_value={"base_dir": asset_root, "index_dir": index_dir},
            ), patch(
                "src.storage.config_store.get_global_model_asset_paths",
                return_value={"global_dir": global_dir},
            ):
                result = prune_legacy_search_index_artifacts(meta)
            self.assertGreaterEqual(result["removed_files"], 2)
            self.assertFalse(os.path.exists(faiss_file))
            self.assertFalse(os.path.isdir(library_root))

    def test_get_library_search_index_status(self):
        with tempfile.TemporaryDirectory() as lib_root:
            meta_v1 = {
                "libraries": {
                    lib_root: {"files": {"clip.mp4": {"asset_state": "ready", "vid": "abc123"}}},
                }
            }
            self.assertEqual(
                get_library_search_index_status(meta_v1, lib_root),
                LIBRARY_SEARCH_INDEX_STATUS_STALE,
            )
            meta_v2_empty = {"search_index_schema_version": SEARCH_INDEX_SCHEMA_V2, "libraries": {lib_root: {"files": {}}}}
            self.assertEqual(
                get_library_search_index_status(meta_v2_empty, lib_root),
                LIBRARY_SEARCH_INDEX_STATUS_NOT_APPLICABLE,
            )
            meta_v2 = {
                "search_index_schema_version": SEARCH_INDEX_SCHEMA_V2,
                "libraries": {
                    lib_root: {"files": {"clip.mp4": {"asset_state": "ready", "vid": "abc123"}}},
                },
            }
            self.assertEqual(get_library_search_index_status(meta_v2, lib_root), LIBRARY_SEARCH_INDEX_STATUS_STALE)
            with patch("src.services.search_index_schema.library_index_is_ready", return_value=True):
                self.assertEqual(get_library_search_index_status(meta_v2, lib_root), LIBRARY_SEARCH_INDEX_STATUS_READY)


if __name__ == "__main__":
    unittest.main()
