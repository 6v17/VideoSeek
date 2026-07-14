import unittest
import os
from unittest.mock import patch

import tests.services_test_support  # noqa: F401 - cv2/faiss stubs
from tests.services_test_support import _model_dirs_from_test_config
from src.services import library_service


class LibraryDetailServiceTests(unittest.TestCase):
    _LANCE_SUMMARY = {
        "ready": False,
        "frame_rows": 0,
        "chunk_rows": 0,
        "indexed_video_count": 0,
        "dimension": 0,
    }

    def setUp(self):
        self._lance_ready_patcher = patch(
            "src.storage.lance_search_index.lance_search_is_ready",
            return_value=False,
        )
        self._lance_summary_patcher = patch(
            "src.storage.lance_store.read_lance_profile_summary",
            return_value=dict(self._LANCE_SUMMARY),
        )
        self._lance_counts_patcher = patch(
            "src.storage.lance_search_index.get_lance_video_row_counts",
            return_value={},
        )
        self._lance_ready_patcher.start()
        self._lance_summary_patcher.start()
        self._lance_counts_patcher.start()

    def tearDown(self):
        self._lance_counts_patcher.stop()
        self._lance_summary_patcher.stop()
        self._lance_ready_patcher.stop()

    @patch("src.storage.lance_search_index.get_lance_indexed_video_ids", return_value=set())
    @patch("src.services.library_service.get_local_model_asset_dirs", side_effect=_model_dirs_from_test_config)
    @patch("src.services.library_service.os.path.exists")
    @patch("src.services.library_service.list_libraries")
    @patch("src.services.library_service.load_config")
    def test_list_local_vector_details_builds_entries(
        self,
        mock_load_config,
        mock_list_libraries,
        mock_exists,
        _mock_get_index,
        _mock_lance_ids,
    ):
        mock_load_config.return_value = {
            "vector_dir": "source/vector",
            "index_dir": "source/index",
        }
        mock_list_libraries.return_value = {
            "D:/videos": {
                "files": {
                    "a.mp4": {"vid": "vid_a"},
                    "b.mp4": {"vid": "vid_b", "asset_state": "sync_failed"},
                }
            }
        }

        def fake_exists(path):
            normalized = str(path).replace("\\", "/")
            if normalized.endswith("/a.mp4"):
                return True
            if normalized.endswith("/b.mp4"):
                return True
            if normalized.endswith("vid_a_vectors.npy"):
                return True
            if normalized.endswith("vid_a_index.faiss"):
                return True
            return False

        mock_exists.side_effect = fake_exists

        result = library_service.list_local_vector_details()

        self.assertEqual(result["total_entries"], 2)
        self.assertEqual(result["entries"][0]["video_rel_path"], "a.mp4")
        self.assertTrue(result["entries"][0]["source_exists"])
        self.assertTrue(result["entries"][0]["legacy_npy_exists"])
        self.assertFalse(result["entries"][0]["vector_exists"])
        self.assertEqual(result["entries"][0]["asset_state"], "broken_asset")
        self.assertFalse(result["entries"][1]["legacy_npy_exists"])
        self.assertEqual(result["entries"][1]["asset_state"], "sync_failed")
        self.assertEqual(result["entries"][1]["sync_failure_reason"], "")

    @patch("src.storage.lance_search_index.get_lance_video_row_counts", return_value={"vid_a": {"frame_count": 12, "chunk_count": 3}})
    @patch("src.storage.lance_search_index.get_lance_indexed_video_ids", return_value=frozenset({"vid_a"}))
    @patch("src.storage.lance_search_index.lance_search_is_ready", return_value=True)
    @patch("src.services.library_service.get_local_model_asset_dirs", side_effect=_model_dirs_from_test_config)
    @patch("src.services.library_service.os.path.exists")
    @patch("src.services.library_service.list_libraries")
    @patch("src.services.library_service.load_config")
    def test_list_local_vector_details_includes_lance_row_counts(
        self,
        mock_load_config,
        mock_list_libraries,
        mock_exists,
        _mock_get_index,
        _mock_lance_ready,
        _mock_lance_ids,
        _mock_lance_counts,
    ):
        mock_load_config.return_value = {
            "vector_dir": "source/vector",
            "index_dir": "source/index",
        }
        mock_list_libraries.return_value = {
            "D:/videos": {
                "files": {
                    "a.mp4": {"vid": "vid_a", "asset_state": "ready"},
                }
            }
        }
        mock_exists.return_value = True

        result = library_service.list_local_vector_details()

        entry = result["entries"][0]
        self.assertEqual(entry["lance_frame_count"], 12)
        self.assertEqual(entry["lance_chunk_count"], 3)

    @patch("src.storage.lance_store.sum_legacy_vector_npy_bytes", return_value=500)
    @patch(
        "src.storage.lance_store.read_lance_profile_summary",
        return_value={
            "ready": True,
            "frame_rows": 12,
            "chunk_rows": 3,
            "indexed_video_count": 1,
            "dimension": 512,
            "lance_dir_bytes": 1000,
        },
    )
    @patch("src.storage.lance_search_index.get_lance_video_row_counts", return_value={"vid_a": {"frame_count": 12, "chunk_count": 3}})
    @patch("src.storage.lance_search_index.get_lance_indexed_video_ids", return_value=frozenset({"vid_a"}))
    @patch("src.storage.lance_search_index.lance_search_is_ready", return_value=True)
    @patch("src.services.library_service.get_local_model_asset_dirs", side_effect=_model_dirs_from_test_config)
    @patch("src.services.library_service.os.path.getsize", return_value=200)
    @patch("src.services.library_service.os.path.exists")
    @patch("src.services.library_service.list_libraries")
    @patch("src.services.library_service.load_config")
    def test_list_local_vector_details_includes_storage_fields(
        self,
        mock_load_config,
        mock_list_libraries,
        mock_exists,
        _mock_getsize,
        _mock_get_index,
        _mock_lance_ready,
        _mock_lance_ids,
        _mock_lance_counts,
        _mock_lance_summary,
        _mock_legacy_dir_bytes,
    ):
        mock_load_config.return_value = {
            "vector_dir": "source/vector",
            "index_dir": "source/index",
        }
        mock_list_libraries.return_value = {
            "D:/videos": {
                "files": {
                    "a.mp4": {"vid": "vid_a", "asset_state": "ready"},
                }
            }
        }
        mock_exists.return_value = True

        result = library_service.list_local_vector_details()
        entry = result["entries"][0]
        summary = result["storage_summary"]
        expected_lance_active = (12 + 3) * 512 * 4 + 12 * 72 + 3 * 64

        self.assertEqual(entry["lance_storage_bytes"], expected_lance_active)
        self.assertEqual(entry["legacy_npy_bytes"], 200)
        self.assertEqual(entry["storage_bytes"], expected_lance_active + 200)
        self.assertEqual(summary["lance_dir_bytes"], 1000)
        self.assertEqual(summary["lance_active_bytes"], expected_lance_active)
        self.assertEqual(summary["legacy_vector_dir_bytes"], 500)
        self.assertEqual(summary["total_storage_bytes"], expected_lance_active + 500)

    @patch("src.storage.lance_store.compact_lance_storage")
    @patch("src.storage.lance_store.garbage_collect_orphan_lance_videos", return_value=[])
    @patch("src.services.library_service.garbage_collect_orphan_library_indexes")
    @patch("src.services.library_service.clear_library_search_index")
    @patch("src.services.library_service.get_local_model_asset_dirs", return_value={"vector_dir": "source/vector", "index_dir": "source/index", "base_dir": "profile"})
    @patch("src.services.library_service.save_model_metadata")
    @patch(
        "src.services.library_service.load_model_metadata",
        return_value={
            "libraries": {
                "D:\\videos": {
                    "files": {
                        "a.mp4": {"vid": "vid_a", "asset_state": "ready"},
                    }
                }
            }
        },
    )
    @patch(
        "src.services.library_service.load_config",
        return_value={
            "meta_file": "source/meta.json",
            "vector_dir": "source/vector",
            "index_dir": "source/index",
        },
    )
    def test_remove_library_compacts_lance_after_deleting_vectors(
        self,
        _mock_load_config,
        mock_load_meta,
        mock_save_meta,
        _mock_get_model_dirs,
        _mock_clear_library_index,
        _mock_gc,
        _mock_gc_orphans,
        mock_compact,
    ):
        deleted = []

        def delete_video_data(video_id, config):
            deleted.append(video_id)

        result = library_service.remove_library("D:\\videos", delete_video_data)

        self.assertTrue(result)
        self.assertEqual(deleted, ["vid_a"])
        _mock_gc_orphans.assert_called_once()
        mock_compact.assert_called_once_with("profile")

    @patch("src.storage.lance_search_index.get_lance_indexed_video_ids", return_value=set())
    @patch("src.services.library_service.get_local_model_asset_dirs", side_effect=_model_dirs_from_test_config)
    @patch("src.services.library_service.os.path.exists")
    @patch("src.services.library_service.list_libraries")
    @patch("src.services.library_service.load_config")
    def test_list_local_vector_details_marks_missing_source(
        self,
        mock_load_config,
        mock_list_libraries,
        mock_exists,
        _mock_get_index,
        _mock_lance_ids,
    ):
        mock_load_config.return_value = {
            "vector_dir": "source/vector",
            "index_dir": "source/index",
        }
        mock_list_libraries.return_value = {
            "D:/videos": {
                "files": {
                    "a.mp4": {"vid": "vid_a", "asset_state": "ready"},
                }
            }
        }

        def fake_exists(path):
            normalized = str(path).replace("\\", "/")
            if normalized.endswith("/a.mp4"):
                return False
            if normalized.endswith("vid_a_vectors.npy"):
                return True
            if normalized.endswith("vid_a_index.faiss"):
                return True
            return False

        mock_exists.side_effect = fake_exists

        result = library_service.list_local_vector_details()

        self.assertFalse(result["entries"][0]["source_exists"])
        self.assertEqual(result["entries"][0]["asset_state"], "missing_source")

    @patch("src.storage.lance_search_index.get_lance_indexed_video_ids", return_value=set())
    @patch("src.services.library_service.get_local_model_asset_dirs", side_effect=_model_dirs_from_test_config)
    @patch("src.services.library_service.os.path.exists")
    @patch("src.services.library_service.list_libraries")
    @patch("src.services.library_service.load_config")
    def test_list_local_vector_details_keeps_sync_failure_reason(
        self,
        mock_load_config,
        mock_list_libraries,
        mock_exists,
        _mock_get_index,
        _mock_lance_ids,
    ):
        mock_load_config.return_value = {
            "vector_dir": "source/vector",
            "index_dir": "source/index",
        }
        mock_list_libraries.return_value = {
            "D:/videos": {
                "files": {
                    "a.mp4": {"vid": "vid_a", "asset_state": "sync_failed", "sync_failure_reason": "too_short"},
                }
            }
        }

        def fake_exists(path):
            normalized = str(path).replace("\\", "/")
            if normalized.endswith("/a.mp4"):
                return True
            return False

        mock_exists.side_effect = fake_exists

        result = library_service.list_local_vector_details()

        self.assertEqual(result["entries"][0]["asset_state"], "sync_failed")
        self.assertEqual(result["entries"][0]["sync_failure_reason"], "too_short")

    @patch("src.storage.lance_search_index.get_lance_indexed_video_ids", return_value=set())
    @patch("src.services.library_service.get_local_model_asset_dirs", side_effect=_model_dirs_from_test_config)
    @patch("src.services.library_service.os.path.exists")
    @patch("src.services.library_service.list_libraries")
    @patch("src.services.library_service.load_config")
    def test_list_local_vector_details_marks_npy_only_as_broken(
        self,
        mock_load_config,
        mock_list_libraries,
        mock_exists,
        _mock_model_dirs,
        _mock_lance_ids,
    ):
        mock_load_config.return_value = {
            "vector_dir": "source/vector",
            "index_dir": "source/index",
        }
        mock_list_libraries.return_value = {
            "D:/videos": {
                "files": {
                    "a.mp4": {"vid": "vid_a", "asset_state": "sync_failed"},
                }
            }
        }

        def fake_exists(path):
            normalized = str(path).replace("\\", "/")
            return normalized.endswith("/a.mp4") or normalized.endswith("vid_a_vectors.npy") or normalized.endswith("vid_a_index.faiss")

        mock_exists.side_effect = fake_exists

        result = library_service.list_local_vector_details()

        self.assertEqual(result["entries"][0]["asset_state"], "sync_failed")
        self.assertFalse(result["entries"][0]["vector_exists"])

    @patch("src.storage.lance_search_index.get_lance_indexed_video_ids", return_value=set())
    @patch("src.services.library_service.get_local_model_asset_dirs", side_effect=_model_dirs_from_test_config)
    @patch("src.services.library_service.os.path.exists")
    @patch("src.services.library_service.list_libraries")
    @patch("src.services.library_service.load_config")
    def test_list_local_vector_details_uses_migrated_storage_dirs(
        self,
        mock_load_config,
        mock_list_libraries,
        mock_exists,
        _mock_get_index,
        _mock_lance_ids,
    ):
        mock_load_config.return_value = {
            "vector_dir": "D:/migrated-root/data/vector",
            "index_dir": "D:/migrated-root/data/index",
        }
        mock_list_libraries.return_value = {
            "D:/videos": {
                "files": {
                    "a.mp4": {"vid": "vid_a", "asset_state": "ready"},
                }
            }
        }

        def fake_exists(path):
            normalized = str(path).replace("\\", "/")
            if normalized == "D:/videos/a.mp4":
                return True
            if normalized == "D:/migrated-root/data/vector/vid_a_vectors.npy":
                return True
            if normalized == "D:/migrated-root/data/index/vid_a_index.faiss":
                return True
            return False

        mock_exists.side_effect = fake_exists

        result = library_service.list_local_vector_details()

        self.assertEqual(result["vector_dir"], os.path.normpath("D:/migrated-root/data/vector"))
        self.assertEqual(result["index_dir"], os.path.normpath("D:/migrated-root/data/index"))
        self.assertEqual(
            result["entries"][0]["legacy_npy_file"],
            os.path.normpath("D:/migrated-root/data/vector/vid_a_vectors.npy"),
        )
        self.assertEqual(result["entries"][0]["index_file"], "")
        self.assertEqual(result["entries"][0]["asset_state"], "broken_asset")
        self.assertFalse(result["entries"][0]["vector_exists"])




if __name__ == "__main__":
    unittest.main()
