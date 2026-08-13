import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")

from src.services.indexing_runtime_status import (
    IndexSyncBusyError,
    clear_index_sync_running,
    get_index_sync_status,
    set_index_sync_running,
    try_acquire_index_sync,
)
from src.services.library_service import (
    list_library_video_entries,
    reconcile_ready_assets_with_lance,
)


class IndexSyncClaimTests(unittest.TestCase):
    def tearDown(self):
        clear_index_sync_running()

    def test_try_acquire_rejects_second_claim(self):
        self.assertTrue(try_acquire_index_sync("D:/lib_a"))
        self.assertFalse(try_acquire_index_sync("D:/lib_b"))
        self.assertTrue(get_index_sync_status()["index_sync_in_progress"])
        clear_index_sync_running()
        self.assertTrue(try_acquire_index_sync("D:/lib_b"))

    def test_set_index_sync_running_raises_when_busy(self):
        set_index_sync_running("D:/lib_a")
        with self.assertRaises(IndexSyncBusyError):
            set_index_sync_running("D:/lib_b")


class ReadyAssetReconcileTests(unittest.TestCase):
    def test_reconcile_demotes_ready_without_lance(self):
        meta = {
            "libraries": {
                "D:/videos": {
                    "files": {
                        "keep.mp4": {"vid": "vid_keep", "asset_state": "ready"},
                        "gone.mp4": {"vid": "vid_gone", "asset_state": "ready"},
                        "failed.mp4": {"vid": "vid_fail", "asset_state": "sync_failed"},
                    }
                }
            }
        }
        with patch(
            "src.services.library_service._lance_indexed_video_ids",
            return_value=frozenset({"vid_keep"}),
        ):
            demoted = reconcile_ready_assets_with_lance(meta, config={})
        self.assertEqual(demoted, 1)
        self.assertEqual(meta["libraries"]["D:/videos"]["files"]["keep.mp4"]["asset_state"], "ready")
        self.assertEqual(meta["libraries"]["D:/videos"]["files"]["gone.mp4"]["asset_state"], "missing_asset")
        self.assertEqual(meta["libraries"]["D:/videos"]["files"]["failed.mp4"]["asset_state"], "sync_failed")

    def test_reconcile_skips_when_lance_unavailable(self):
        meta = {
            "libraries": {
                "D:/videos": {
                    "files": {"a.mp4": {"vid": "vid_a", "asset_state": "ready"}},
                }
            }
        }
        with patch("src.services.library_service._lance_indexed_video_ids", return_value=None):
            self.assertEqual(reconcile_ready_assets_with_lance(meta, config={}), 0)
        self.assertEqual(meta["libraries"]["D:/videos"]["files"]["a.mp4"]["asset_state"], "ready")

    def test_list_library_video_entries_demotes_stale_ready(self):
        lib_root = os.path.abspath(os.path.join(tempfile.gettempdir(), "videoseek_list_ready_lib"))
        os.makedirs(lib_root, exist_ok=True)
        video_path = os.path.join(lib_root, "clip.mp4")
        if not os.path.isfile(video_path):
            with open(video_path, "wb") as handle:
                handle.write(b"fake")
        meta = {
            "libraries": {
                lib_root: {
                    "files": {
                        "clip.mp4": {"vid": "vid_missing_lance", "asset_state": "ready"},
                    }
                }
            }
        }
        with (
            patch("src.services.library_service.register_library_videos", return_value={"changed": False}),
            patch("src.services.library_service.load_model_metadata", return_value=meta),
            patch("src.services.library_service.load_config", return_value={}),
            patch(
                "src.services.library_service._lance_indexed_video_ids",
                return_value=frozenset(),
            ),
            patch("src.services.library_service.get_index_sync_status", return_value={"index_sync_in_progress": False}),
            patch("src.services.library_service.save_model_metadata") as save_meta,
        ):
            entries = list_library_video_entries(register=False)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["asset_state"], "missing_asset")
        self.assertEqual(meta["libraries"][lib_root]["files"]["clip.mp4"]["asset_state"], "missing_asset")
        save_meta.assert_called_once()


class LanceUpsertRestoreTests(unittest.TestCase):
    def setUp(self):
        from src.storage import lance_store

        lance_store._RECOVERED_UPSERT_PROFILES.clear()

    def tearDown(self):
        from src.storage import lance_store
        from src.storage.lance_search_index import _INDEXED_VIDEO_IDS_CACHE

        lance_store._RECOVERED_UPSERT_PROFILES.clear()
        _INDEXED_VIDEO_IDS_CACHE.clear()

    def test_upsert_restores_via_journal_when_append_fails(self):
        try:
            import lancedb  # noqa: F401
        except ImportError:
            self.skipTest("lancedb not installed")

        from src.storage.lance_search_index import get_lance_indexed_video_ids
        from src.storage.lance_store import (
            FRAMES_TABLE_NAME,
            upsert_profile_video_vectors_from_arrays,
        )

        vectors = np.random.randn(4, 8).astype(np.float32)
        timestamps = np.asarray([0.0, 1.0, 2.0, 3.0], dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = os.path.join(tmp, "profile")
            os.makedirs(profile_dir, exist_ok=True)

            with patch(
                "src.storage.config_store.get_local_model_asset_dirs",
                return_value={"base_dir": profile_dir, "vector_dir": os.path.join(profile_dir, "vector")},
            ):
                first = upsert_profile_video_vectors_from_arrays(
                    "vid_restore",
                    vectors,
                    timestamps,
                    config={},
                    library_path=tmp,
                    video_path=os.path.join(tmp, "clip.mp4"),
                    chunks=[],
                )
                self.assertFalse(first.get("error"))
                self.assertIn("vid_restore", get_lance_indexed_video_ids(profile_dir))

                import src.storage.lance_store as lance_store

                real_append = lance_store._append_rows_to_table

                def _fail_frames_append(db, table_name, schema, rows):
                    if table_name == FRAMES_TABLE_NAME:
                        raise RuntimeError("simulated append failure")
                    return real_append(db, table_name, schema, rows)

                with patch.object(lance_store, "_append_rows_to_table", side_effect=_fail_frames_append):
                    failed = upsert_profile_video_vectors_from_arrays(
                        "vid_restore",
                        np.random.randn(2, 8).astype(np.float32),
                        np.asarray([0.0, 1.0], dtype=np.float32),
                        config={},
                        library_path=tmp,
                        video_path=os.path.join(tmp, "clip.mp4"),
                        chunks=[],
                    )
                self.assertTrue(failed.get("error"))
                from src.storage.lance_search_index import _INDEXED_VIDEO_IDS_CACHE

                _INDEXED_VIDEO_IDS_CACHE.clear()
                self.assertIn("vid_restore", get_lance_indexed_video_ids(profile_dir))

    def test_recover_interrupted_upsert_journal_after_process_kill(self):
        """Simulate kill after delete: journal remains; recovery restores other videos too."""
        try:
            import lancedb  # noqa: F401
        except ImportError:
            self.skipTest("lancedb not installed")

        from src.storage.lance_search_index import get_lance_indexed_video_ids
        from src.storage.lance_store import (
            FRAMES_TABLE_NAME,
            _delete_video_rows,
            _table_version,
            _write_upsert_journal,
            recover_interrupted_lance_upserts,
            upsert_profile_video_vectors_from_arrays,
        )
        from src.storage import lance_store

        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = os.path.join(tmp, "profile")
            os.makedirs(profile_dir, exist_ok=True)
            dirs = {"base_dir": profile_dir, "vector_dir": os.path.join(profile_dir, "vector")}
            with patch("src.storage.config_store.get_local_model_asset_dirs", return_value=dirs):
                for vid, n in (("vid_keep", 3), ("vid_victim", 5)):
                    result = upsert_profile_video_vectors_from_arrays(
                        vid,
                        np.random.randn(n, 8).astype(np.float32),
                        np.arange(n, dtype=np.float32),
                        config={},
                        library_path=tmp,
                        video_path=os.path.join(tmp, f"{vid}.mp4"),
                        chunks=[],
                    )
                    self.assertFalse(result.get("error"), result)

                ids_before = get_lance_indexed_video_ids(profile_dir)
                self.assertEqual(ids_before, frozenset({"vid_keep", "vid_victim"}))

                # Simulate crash: journal written, delete done, process dies before append/clear.
                db = lance_store._connect_lance(profile_dir)
                pre_version = _table_version(db, FRAMES_TABLE_NAME)
                _write_upsert_journal(
                    profile_dir,
                    {
                        "video_id": "vid_victim",
                        "tables": [{"table": FRAMES_TABLE_NAME, "pre_version": pre_version}],
                    },
                )
                _delete_video_rows(db, FRAMES_TABLE_NAME, "vid_victim")
                from src.storage.lance_search_index import _INDEXED_VIDEO_IDS_CACHE

                _INDEXED_VIDEO_IDS_CACHE.clear()
                self.assertNotIn("vid_victim", get_lance_indexed_video_ids(profile_dir))
                self.assertIn("vid_keep", get_lance_indexed_video_ids(profile_dir))

                # New process: recover on connect/begin.
                lance_store._RECOVERED_UPSERT_PROFILES.clear()
                self.assertTrue(recover_interrupted_lance_upserts(profile_dir))
                _INDEXED_VIDEO_IDS_CACHE.clear()
                ids_after = get_lance_indexed_video_ids(profile_dir)
                self.assertEqual(ids_after, frozenset({"vid_keep", "vid_victim"}))
                self.assertFalse(os.path.isfile(lance_store._upsert_journal_path(profile_dir)))


if __name__ == "__main__":
    unittest.main()
