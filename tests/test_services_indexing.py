import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

import numpy as np

import tests.services_test_support  # noqa: F401 - cv2/faiss stubs
from src.services import indexing_service, library_service
from src.workflows import update_video
from src import utils


class IndexingServiceTests(unittest.TestCase):
    @patch("src.services.library_service.save_model_metadata")
    @patch("src.services.library_service.load_model_metadata", return_value={"libraries": {"D:\\videos": {"files": {}}}})
    @patch("src.services.library_service.load_config", return_value={"meta_file": "source/meta.json"})
    def test_add_library_rejects_exact_duplicate(
        self,
        _mock_load_config,
        _mock_load_meta,
        mock_save_meta,
    ):
        result = library_service.add_library("D:\\videos")

        self.assertEqual(result["added"], False)
        self.assertEqual(result["reason"], "exists")
        mock_save_meta.assert_not_called()

    @patch("src.services.library_service.save_model_metadata")
    @patch("src.services.library_service.load_model_metadata", return_value={"libraries": {"D:\\videos": {"files": {}}}})
    @patch("src.services.library_service.load_config", return_value={"meta_file": "source/meta.json"})
    def test_add_library_rejects_child_directory_overlap(
        self,
        _mock_load_config,
        _mock_load_meta,
        mock_save_meta,
    ):
        result = library_service.add_library("D:\\videos\\anime")

        self.assertEqual(result["added"], False)
        self.assertEqual(result["reason"], "overlap")
        self.assertEqual(utils.canonicalize_library_path(result["conflict_path"]), utils.canonicalize_library_path("D:\\videos"))
        mock_save_meta.assert_not_called()

    @patch("src.services.library_service.save_model_metadata")
    @patch("src.services.library_service.load_model_metadata", return_value={"libraries": {"D:\\videos\\anime": {"files": {}}}})
    @patch("src.services.library_service.load_config", return_value={"meta_file": "source/meta.json"})
    def test_add_library_rejects_parent_directory_overlap(
        self,
        _mock_load_config,
        _mock_load_meta,
        mock_save_meta,
    ):
        result = library_service.add_library("D:\\videos")

        self.assertEqual(result["added"], False)
        self.assertEqual(result["reason"], "overlap")
        self.assertEqual(
            utils.canonicalize_library_path(result["conflict_path"]),
            utils.canonicalize_library_path("D:\\videos\\anime"),
        )
        mock_save_meta.assert_not_called()

    @patch("src.services.library_service.save_model_metadata")
    @patch("src.services.library_service.load_model_metadata", return_value={"libraries": {"E:\\videos": {"files": {}}}})
    @patch("src.services.library_service.load_config", return_value={"meta_file": "source/meta.json"})
    def test_add_library_allows_non_overlapping_directory_on_different_drive(
        self,
        _mock_load_config,
        _mock_load_meta,
        mock_save_meta,
    ):
        result = library_service.add_library("D:\\movies")

        self.assertEqual(result["added"], True)
        self.assertEqual(result["reason"], "")
        mock_save_meta.assert_called_once()

    @patch("src.services.library_service.save_model_metadata")
    @patch("src.services.library_service.load_model_metadata", return_value={"libraries": {}})
    @patch("src.services.library_service.load_config", return_value={"meta_file": "source/meta.json"})
    def test_add_library_keeps_global_index_state_untouched(
        self,
        _mock_load_config,
        mock_load_meta,
        mock_save_meta,
    ):
        result = library_service.add_library("D:\\videos")

        self.assertTrue(result["added"])
        self.assertNotIn("global_index_state", mock_load_meta.return_value)
        mock_save_meta.assert_called_once()

    @patch("src.services.library_service.garbage_collect_orphan_library_indexes")
    @patch("src.services.library_service.clear_library_search_index")
    @patch("src.services.library_service.get_local_model_asset_dirs", return_value={"vector_dir": "source/vector", "index_dir": "source/index", "base_dir": "x"})
    @patch("src.services.library_service.os.path.exists", return_value=True)
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
    def test_remove_library_clears_library_search_index(
        self,
        _mock_load_config,
        mock_load_meta,
        mock_save_meta,
        _mock_exists,
        _mock_get_model_dirs,
        mock_clear_library_index,
        _mock_gc,
    ):
        result = library_service.remove_library("D:\\videos", lambda *_args, **_kwargs: None)

        self.assertTrue(result)
        mock_clear_library_index.assert_called_once()
        self.assertEqual(mock_clear_library_index.call_args.kwargs["config"], _mock_load_config.return_value)
        mock_save_meta.assert_called_once()

    @patch("src.services.library_service.garbage_collect_orphan_library_indexes")
    @patch("src.services.library_service.clear_library_search_index")
    @patch("src.services.library_service.get_local_model_asset_dirs", return_value={"vector_dir": "source/vector", "index_dir": "source/index", "base_dir": "x"})
    @patch("src.services.library_service.os.path.exists", return_value=False)
    @patch("src.services.library_service.save_model_metadata")
    @patch(
        "src.services.library_service.load_model_metadata",
        return_value={
            "libraries": {
                "D:\\videos": {
                    "files": {},
                    "index_state": "pending",
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
    def test_remove_library_keeps_global_index_state_untouched_for_pending_empty_library(
        self,
        _mock_load_config,
        mock_load_meta,
        mock_save_meta,
        _mock_exists,
        _mock_get_model_dirs,
        mock_clear_library_index,
        _mock_gc,
    ):
        result = library_service.remove_library("D:\\videos", lambda *_args, **_kwargs: None)

        self.assertTrue(result)
        mock_clear_library_index.assert_called_once()
        self.assertNotIn("global_index_state", mock_load_meta.return_value)
        mock_save_meta.assert_called_once()

    def test_count_video_id_refs_shared_across_libraries(self):
        meta = {
            "libraries": {
                "D:\\lib_a": {"files": {"a.mp4": {"vid": "shared"}}},
                "D:\\lib_b": {"files": {"b.mp4": {"vid": "shared"}, "c.mp4": {"vid": "only_b"}}},
            }
        }
        self.assertEqual(library_service.count_video_id_refs(meta, "shared"), 2)
        self.assertTrue(library_service.video_id_is_shared(meta, "shared"))
        self.assertEqual(
            library_service.count_video_id_refs(
                meta,
                "shared",
                exclude_library_path="D:\\lib_a",
            ),
            1,
        )
        self.assertEqual(library_service.count_video_id_refs(meta, "only_b"), 1)
        self.assertFalse(library_service.video_id_is_shared(meta, "only_b"))

    @patch("src.storage.lance_store.compact_lance_storage")
    @patch("src.storage.lance_store.garbage_collect_orphan_lance_videos", return_value=[])
    @patch("src.services.library_service.garbage_collect_orphan_library_indexes")
    @patch("src.services.library_service.clear_library_search_index")
    @patch(
        "src.services.library_service.get_local_model_asset_dirs",
        return_value={"vector_dir": "source/vector", "index_dir": "source/index", "base_dir": "profile"},
    )
    @patch("src.services.library_service.save_model_metadata")
    @patch(
        "src.services.library_service.load_model_metadata",
        return_value={
            "libraries": {
                "D:\\lib_a": {"files": {"a.mp4": {"vid": "shared_vid", "asset_state": "ready"}}},
                "D:\\lib_b": {"files": {"copy.mp4": {"vid": "shared_vid", "asset_state": "ready"}}},
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
    def test_remove_library_keeps_shared_video_payload(
        self,
        _mock_load_config,
        mock_load_meta,
        mock_save_meta,
        _mock_get_model_dirs,
        _mock_clear,
        _mock_gc,
        _mock_gc_orphans,
        mock_compact,
    ):
        deleted = []

        def delete_video_data(video_id, config, **_kwargs):
            deleted.append(video_id)

        result = library_service.remove_library("D:\\lib_a", delete_video_data)

        self.assertTrue(result)
        self.assertEqual(deleted, [])
        mock_compact.assert_not_called()
        saved_meta = mock_save_meta.call_args.args[0]
        libs = library_service._normalize_library_map(saved_meta.get("libraries", {}))
        self.assertNotIn(utils.canonicalize_library_path("D:\\lib_a"), libs)
        kept_b = libs[utils.canonicalize_library_path("D:\\lib_b")]["files"]
        self.assertIn(
            "shared_vid",
            {str(info.get("vid") or "") for info in kept_b.values()},
        )

    @patch("src.services.library_service.get_library_search_index_status", return_value="stale")
    @patch("src.services.library_service.load_model_metadata", return_value={"search_index_schema_version": 2, "libraries": {}})
    @patch("src.services.library_service.load_config", return_value={})
    @patch("src.services.library_service.os.path.exists", return_value=True)
    def test_resolve_library_card_status_shows_stale_when_library_index_missing(
        self,
        _mock_exists,
        _mock_config,
        _mock_meta,
        _mock_status,
    ):
        texts = {"lib_ready": "Ready", "lib_search_index_stale": "Library index stale", "delete": "delete"}
        label, state = library_service.resolve_library_card_status(
            "D:\\videos",
            {"files": {"a.mp4": {"asset_state": "ready"}}, "index_state": "ready"},
            texts,
            meta=_mock_meta.return_value,
            config=_mock_config.return_value,
        )
        self.assertEqual(label, "Library index stale")
        self.assertEqual(state, "partial")

    @patch("src.services.library_service.get_index_sync_status")
    def test_resolve_library_card_status_shows_sync_progress(self, mock_sync_status):
        mock_sync_status.return_value = {
            "index_sync_in_progress": True,
            "index_sync_target_library_path": "",
            "index_sync_progress_current": 2341,
            "index_sync_progress_total": 5000,
        }
        texts = {
            "lib_syncing_progress": "Syncing {current}/{total}",
            "lib_syncing": "Syncing",
            "delete": "delete",
        }
        label, state = library_service.resolve_library_card_status(
            "D:\\videos",
            {"files": {"a.mp4": {"asset_state": "ready"}}, "index_state": "partial"},
            texts,
        )
        self.assertEqual(label, "Syncing 2341/5000")
        self.assertEqual(state, "partial")

    def test_cleanup_missing_library_files_removes_deleted_entries(self):
        meta = {
            "libraries": {
                "C:\\videos": {
                    "files": {
                        "keep.mp4": {"vid": "keep"},
                        "missing.mp4": {"vid": "gone"},
                    }
                }
            }
        }

        def fake_exists(path):
            normalized = str(path).replace("/", "\\")
            if normalized == "C:\\videos":
                return True
            return normalized.endswith("keep.mp4")

        with patch("src.services.indexing_service.os.path.exists", side_effect=fake_exists):
            removed = list(indexing_service.cleanup_missing_library_files(meta, {}, None))

        self.assertEqual(removed, ["gone"])
        self.assertIn("keep.mp4", meta["libraries"]["C:\\videos"]["files"])
        self.assertNotIn("missing.mp4", meta["libraries"]["C:\\videos"]["files"])

    def test_cleanup_missing_library_files_can_limit_to_selected_entries(self):
        meta = {
            "libraries": {
                "C:\\videos": {
                    "files": {
                        "missing_a.mp4": {"vid": "gone_a"},
                        "missing_b.mp4": {"vid": "gone_b"},
                    }
                }
            }
        }

        def fake_exists(path):
            return str(path).replace("/", "\\") == "C:\\videos"

        with patch("src.services.indexing_service.os.path.exists", side_effect=fake_exists):
            removed = list(
                indexing_service.cleanup_missing_library_files(
                    meta,
                    {},
                    None,
                    selected_entries=[
                        {
                            "library_path": "C:\\videos",
                            "video_rel_path": "missing_b.mp4",
                        }
                    ],
                )
            )

        self.assertEqual(removed, ["gone_b"])
        self.assertIn("missing_a.mp4", meta["libraries"]["C:\\videos"]["files"])
        self.assertNotIn("missing_b.mp4", meta["libraries"]["C:\\videos"]["files"])

    def test_cleanup_missing_library_files_keeps_entries_when_library_root_is_offline(self):
        meta = {
            "libraries": {
                "E:\\videos": {
                    "files": {
                        "movie.mp4": {"vid": "keep"},
                    }
                }
            }
        }

        with patch("src.services.indexing_service.os.path.exists", return_value=False):
            removed = list(indexing_service.cleanup_missing_library_files(meta, {}, None))

        self.assertEqual(removed, [])
        self.assertIn("movie.mp4", meta["libraries"]["E:\\videos"]["files"])

    def test_list_missing_library_files_skips_offline_library_roots(self):
        meta = {
            "libraries": {
                "D:\\online": {
                    "files": {
                        "missing.mp4": {"vid": "gone"},
                    }
                },
                "E:\\offline": {
                    "files": {
                        "keep.mp4": {"vid": "keep"},
                    }
                },
            }
        }

        def fake_exists(path):
            if path == "D:\\online":
                return True
            if path == "E:\\offline":
                return False
            return False

        with patch("src.services.indexing_service.os.path.exists", side_effect=fake_exists):
            missing = list(indexing_service.list_missing_library_files(meta, {}, None))

        self.assertEqual(
            missing,
            [
                {
                    "library_path": "D:\\online",
                    "video_rel_path": "missing.mp4",
                    "abs_path": "D:\\online\\missing.mp4",
                    "video_id": "gone",
                }
            ],
        )

    def test_discover_video_files_filters_supported_extensions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "clip.mp4").write_bytes(b"")
            (root / "note.txt").write_text("ignore", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "scene.mkv").write_bytes(b"")
            macosx = root / "__MACOSX"
            macosx.mkdir()
            (macosx / "skip.mp4").write_bytes(b"")

            result = indexing_service.discover_video_files(str(root))

        self.assertEqual(
            sorted(Path(path).name for path in result),
            ["clip.mp4", "scene.mkv"],
        )

    def test_load_library_video_file_list_reuses_cached_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "clip.mp4").write_bytes(b"")
            lib_data = {}
            first = indexing_service.load_library_video_file_list(str(root), lib_data, refresh=True)
            with patch("src.services.indexing_service.discover_video_files") as mock_discover:
                mock_discover.side_effect = AssertionError("discover_video_files should not run for warm cache")
                second = indexing_service.load_library_video_file_list(str(root), lib_data, refresh=False)
            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 1)
            self.assertIn("discover_cache", lib_data)
            self.assertIn("dir_snapshots", lib_data["discover_cache"])

    def test_discover_video_files_incremental_reuses_unchanged_subtree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stable = root / "stable"
            changed = root / "changed"
            stable.mkdir()
            changed.mkdir()
            (stable / "keep.mp4").write_bytes(b"")
            (changed / "old.mp4").write_bytes(b"")
            lib_data = {}
            indexing_service.refresh_library_video_file_list(str(root), lib_data)
            (changed / "old.mp4").unlink()
            (changed / "new.mp4").write_bytes(b"")

            result = indexing_service.discover_video_files_incremental(str(root), lib_data)

            self.assertEqual(sorted(Path(path).name for path in result), ["keep.mp4", "new.mp4"])
            self.assertIn("stable", lib_data["discover_cache"]["dir_snapshots"])
            self.assertIn("changed", lib_data["discover_cache"]["dir_snapshots"])

    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    @patch("src.services.indexing_service.get_legacy_video_hash", return_value="")
    @patch("src.services.indexing_service.get_video_hash", return_value="vid_a")
    @patch("src.services.indexing_service.discover_video_files")
    @patch("src.services.indexing_service.os.path.exists")
    def test_reconcile_library_file_paths_uses_known_abs_paths(
        self,
        mock_exists,
        mock_discover,
        _mock_video_hash,
        _mock_legacy_hash,
        _mock_valid_source,
    ):
        mock_discover.side_effect = AssertionError("discover_video_files should not run when known paths provided")
        root_path = "D:\\videos"
        lib_files = {"old\\clip.mp4": {"vid": "vid_a", "asset_state": "ready", "mod_time": 100.0}}

        def fake_exists(path):
            normalized = str(path).replace("\\", "/")
            if normalized == "D:/videos/new/clip.mp4":
                return True
            if normalized == "D:/videos/old/clip.mp4":
                return False
            return normalized == "D:/videos"

        mock_exists.side_effect = fake_exists

        reconciled = indexing_service.reconcile_library_file_paths(
            root_path,
            lib_files,
            known_abs_paths=["D:\\videos\\new\\clip.mp4"],
        )

        self.assertEqual(reconciled, 1)
        self.assertIn("new/clip.mp4", lib_files)
        mock_discover.assert_not_called()

    @patch("src.storage.lance_store.end_lance_index_batch")
    @patch("src.storage.lance_store.begin_lance_index_batch")
    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile"})
    @patch("src.services.indexing_service.load_video_chunks_by_id", return_value=[])
    @patch("src.services.indexing_service.process_single_video")
    @patch("src.services.indexing_service.cleanup_invalid_library_files", return_value=iter(()))
    @patch("src.services.indexing_service._collect_library_scan_plan")
    def test_scan_target_libraries_uses_global_file_progress(
        self,
        mock_scan_plan,
        _mock_cleanup_invalid,
        mock_process_single_video,
        _mock_load_chunks,
        _mock_model_dirs,
        _mock_begin_batch,
        _mock_end_batch,
    ):
        meta = {"libraries": {"D:\\videos": {"files": {}}}}
        progress_events = []
        mock_scan_plan.return_value = [
            ("D:\\videos", meta["libraries"]["D:\\videos"], ["D:\\videos\\a.mp4", "D:\\videos\\b.mp4"]),
        ]
        mock_process_single_video.return_value = (None, None, False, False)

        indexing_service.scan_target_libraries(
            meta,
            {},
            lambda _path: "vid_a",
            persist_meta_callback=None,
            progress_callback=lambda value, text: progress_events.append((value, text)),
        )

        self.assertEqual(mock_process_single_video.call_count, 2)
        first_kwargs = mock_process_single_video.call_args_list[0].kwargs
        second_kwargs = mock_process_single_video.call_args_list[1].kwargs
        self.assertEqual(first_kwargs["file_index"], 1)
        self.assertEqual(first_kwargs["file_total"], 2)
        self.assertEqual(second_kwargs["file_index"], 2)
        self.assertEqual(second_kwargs["file_total"], 2)

    @patch("src.storage.lance_store.end_lance_index_batch")
    @patch("src.storage.lance_store.begin_lance_index_batch")
    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile"})
    @patch("src.services.indexing_service.process_single_video")
    @patch("src.services.indexing_service.cleanup_invalid_library_files", return_value=iter(()))
    @patch("src.services.indexing_service._collect_library_scan_plan")
    def test_scan_target_libraries_marks_only_active_library_partial_on_stop(
        self,
        mock_scan_plan,
        _mock_cleanup_invalid,
        mock_process_single_video,
        _mock_model_dirs,
        _mock_begin_batch,
        _mock_end_batch,
    ):
        meta = {
            "libraries": {
                "D:\\done": {"files": {"a.mp4": {"vid": "v1"}}, "index_state": "ready"},
                "D:\\active": {"files": {}, "index_state": "ready"},
                "D:\\waiting": {"files": {"b.mp4": {"vid": "v2"}}, "index_state": "ready"},
            }
        }
        mock_scan_plan.return_value = [
            ("D:\\done", meta["libraries"]["D:\\done"], ["D:\\done\\a.mp4"]),
            ("D:\\active", meta["libraries"]["D:\\active"], ["D:\\active\\c.mp4"]),
            ("D:\\waiting", meta["libraries"]["D:\\waiting"], ["D:\\waiting\\b.mp4"]),
        ]
        mock_process_single_video.return_value = (None, None, False, False)
        stop_after = {"count": 0}

        def stop_callback():
            stop_after["count"] += 1
            return stop_after["count"] >= 4

        with self.assertRaises(indexing_service.IndexUpdateInterrupted):
            indexing_service.scan_target_libraries(
                meta,
                {},
                lambda _path: "vid",
                should_stop_callback=stop_callback,
            )

        self.assertEqual(meta["libraries"]["D:\\done"]["index_state"], "ready")
        self.assertEqual(meta["libraries"]["D:\\active"]["index_state"], "partial")
        self.assertEqual(meta["libraries"]["D:\\waiting"]["index_state"], "ready")

    def test_repair_false_partial_library_states_when_all_libraries_stuck_partial(self):
        meta = {
            "libraries": {
                "D:\\a": {"files": {"a.mp4": {"vid": "v1"}}, "index_state": "partial"},
                "D:\\b": {"files": {"b.mp4": {"vid": "v2"}}, "index_state": "partial"},
            }
        }
        with patch("src.services.library_service.get_index_sync_status", return_value={"index_sync_in_progress": False}):
            changed = library_service._repair_false_partial_library_states(meta)
        self.assertTrue(changed)
        self.assertEqual(meta["libraries"]["D:\\a"]["index_state"], "ready")
        self.assertEqual(meta["libraries"]["D:\\b"]["index_state"], "ready")

    @patch("src.services.indexing_service._is_valid_video_source", return_value=False)
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    def test_process_single_video_skips_invalid_video_source_before_hashing(
        self,
        _mock_getmtime,
        _mock_stream,
    ):
        lib_files = {}

        vectors, timestamps, metadata_updated, search_assets_changed = indexing_service.process_single_video(
            "D:\\videos\\._clip.mp4",
            "._clip.mp4",
            lib_files,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: self.fail("get_video_id should not be called for invalid sources"),
        )

        self.assertIsNone(vectors)
        self.assertIsNone(timestamps)
        self.assertFalse(metadata_updated)
        self.assertFalse(search_assets_changed)
        self.assertEqual(lib_files, {})

    @patch("src.services.indexing_service._is_valid_video_source", return_value=False)
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    def test_process_single_video_reports_invalid_video_issue(
        self,
        _mock_getmtime,
        _mock_stream,
    ):
        issues = []

        vectors, timestamps, metadata_updated, search_assets_changed = indexing_service.process_single_video(
            "D:\\videos\\._clip.mp4",
            "._clip.mp4",
            {},
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: self.fail("get_video_id should not be called for invalid sources"),
            library_path="D:\\videos",
            issue_callback=issues.append,
        )

        self.assertIsNone(vectors)
        self.assertIsNone(timestamps)
        self.assertFalse(metadata_updated)
        self.assertFalse(search_assets_changed)
        self.assertEqual(
            issues,
            [
                {
                    "library_path": "D:\\videos",
                    "video_rel_path": "._clip.mp4",
                    "abs_path": "D:\\videos\\._clip.mp4",
                    "action": "skipped",
                    "reason": "invalid_video_source",
                    "detail": "Missing file or unsupported extension.",
                }
            ],
        )

    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile", "index_dir": "index", "vector_dir": "vector"})
    @patch("src.services.indexing_service.get_video_duration_seconds", return_value=60.0)
    @patch("src.services.indexing_service.generate_vectors_and_index_for_video", return_value=([], [], None, []))
    @patch("src.services.indexing_service.get_legacy_video_hash", return_value="")
    @patch("src.services.indexing_service.get_video_hash", return_value="vid_a")
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    def test_process_single_video_marks_sync_failed_when_generation_returns_empty_data(
        self,
        _mock_stream,
        _mock_getmtime,
        _mock_video_hash,
        _mock_legacy_hash,
        _mock_generate,
        _mock_duration,
        _mock_model_dirs,
    ):
        lib_files = {}

        vectors, timestamps, metadata_updated, search_assets_changed = indexing_service.process_single_video(
            "D:\\videos\\clip.mp4",
            "clip.mp4",
            lib_files,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: "vid_a",
        )

        self.assertIsNone(vectors)
        self.assertIsNone(timestamps)
        self.assertTrue(metadata_updated)
        self.assertFalse(search_assets_changed)
        self.assertEqual(lib_files["clip.mp4"]["asset_state"], "sync_failed")
        self.assertEqual(lib_files["clip.mp4"]["vid"], "vid_a")
        self.assertEqual(lib_files["clip.mp4"]["sync_failure_reason"], "no_frames")

    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile", "index_dir": "index", "vector_dir": "vector"})
    @patch("src.services.indexing_service.get_video_duration_seconds", return_value=0.6)
    @patch("src.services.indexing_service.generate_vectors_and_index_for_video", return_value=([], [], None, []))
    @patch("src.services.indexing_service.get_legacy_video_hash", return_value="")
    @patch("src.services.indexing_service.get_video_hash", return_value="vid_a")
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    def test_process_single_video_marks_too_short_reason_for_subsecond_video(
        self,
        _mock_stream,
        _mock_getmtime,
        _mock_video_hash,
        _mock_legacy_hash,
        _mock_generate,
        _mock_duration,
        _mock_model_dirs,
    ):
        lib_files = {}

        vectors, timestamps, metadata_updated, search_assets_changed = indexing_service.process_single_video(
            "D:\\videos\\clip.mp4",
            "clip.mp4",
            lib_files,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: "vid_a",
        )

        self.assertIsNone(vectors)
        self.assertIsNone(timestamps)
        self.assertTrue(metadata_updated)
        self.assertFalse(search_assets_changed)
        self.assertEqual(lib_files["clip.mp4"]["sync_failure_reason"], "too_short")

    @patch("src.storage.lance_store.upsert_profile_video_vectors_from_arrays", return_value={"error": "boom", "video_id": "vid_a"})
    def test_sync_video_vectors_to_lance_returns_false_on_upsert_error(self, _mock_upsert):
        ok = indexing_service._sync_video_vectors_to_lance(
            "vid_a",
            {},
            "D:\\lib",
            "D:\\lib\\clip.mp4",
            vectors=np.array([[1.0, 0.0]], dtype=np.float32),
            timestamps=np.array([0.0], dtype=np.float32),
        )
        self.assertFalse(ok)

    @patch("src.services.indexing_service._load_vectors_from_disk")
    @patch("src.services.indexing_service.get_legacy_video_hash", return_value="legacy")
    @patch("src.services.indexing_service.get_video_hash", return_value="vid_new")
    def test_resolve_reusable_cached_vectors_returns_disk_and_canonical_ids(
        self,
        _mock_hash,
        _mock_legacy,
        mock_load,
    ):
        vectors = np.array([[1.0, 0.0]], dtype=np.float32)
        timestamps = np.array([0.0], dtype=np.float32)

        def _load(video_id, _config):
            if video_id == "vid_old":
                return vectors, timestamps, "unused.npy"
            return None, None, "unused.npy"

        mock_load.side_effect = _load
        cached = indexing_service._resolve_reusable_cached_vectors(
            "D:\\lib\\clip.mp4",
            {"vid": "vid_old"},
            {},
        )
        self.assertEqual(cached["canonical_vid"], "vid_new")
        self.assertEqual(cached["disk_vid"], "vid_old")
        self.assertEqual(cached["vectors"].tolist(), vectors.tolist())

    @patch("src.services.indexing_service._ensure_video_chunks", return_value=([], False, {}))
    @patch("src.services.indexing_service._sync_video_vectors_to_lance", return_value=True)
    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile", "index_dir": "index", "vector_dir": "vector"})
    @patch("src.services.indexing_service._resolve_reusable_cached_vectors")
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    def test_process_single_video_syncs_lance_when_reusing_vectors(
        self,
        _mock_stream,
        _mock_getmtime,
        mock_reuse,
        _mock_model_dirs,
        mock_sync_lance,
        _mock_chunks,
    ):
        vectors = np.array([[1.0, 0.0]], dtype=np.float32)
        timestamps = np.array([0.0], dtype=np.float32)
        mock_reuse.return_value = {
            "canonical_vid": "vid_a",
            "disk_vid": "vid_a",
            "vectors": vectors,
            "timestamps": timestamps,
        }
        lib_files = {"clip.mp4": {"vid": "vid_a", "mod_time": 123.0}}

        reused_vectors, reused_timestamps, metadata_updated, search_assets_changed = indexing_service.process_single_video(
            "D:\\videos\\clip.mp4",
            "clip.mp4",
            lib_files,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: "vid_a",
        )

        self.assertTrue(metadata_updated)
        self.assertFalse(search_assets_changed)
        self.assertEqual(reused_vectors.tolist(), vectors.tolist())
        self.assertEqual(reused_timestamps.tolist(), timestamps.tolist())
        self.assertEqual(lib_files["clip.mp4"]["asset_state"], "ready")
        mock_sync_lance.assert_called_once()
        self.assertEqual(lib_files["clip.mp4"]["vid"], "vid_a")

    @patch("src.services.indexing_service._ensure_video_chunks", return_value=([], False, {}))
    @patch("src.services.indexing_service._sync_video_vectors_to_lance", return_value=False)
    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile", "index_dir": "index", "vector_dir": "vector"})
    @patch("src.services.indexing_service._resolve_reusable_cached_vectors")
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    def test_process_single_video_marks_sync_failed_when_lance_reuse_sync_fails(
        self,
        _mock_stream,
        _mock_getmtime,
        mock_reuse,
        _mock_model_dirs,
        mock_sync_lance,
        _mock_chunks,
    ):
        vectors = np.array([[1.0, 0.0]], dtype=np.float32)
        timestamps = np.array([0.0], dtype=np.float32)
        mock_reuse.return_value = {
            "canonical_vid": "vid_a",
            "disk_vid": "vid_a",
            "vectors": vectors,
            "timestamps": timestamps,
        }
        lib_files = {"clip.mp4": {"vid": "vid_a", "mod_time": 123.0}}

        reused_vectors, reused_timestamps, metadata_updated, search_assets_changed = indexing_service.process_single_video(
            "D:\\videos\\clip.mp4",
            "clip.mp4",
            lib_files,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: "vid_a",
        )

        self.assertIsNone(reused_vectors)
        self.assertIsNone(reused_timestamps)
        self.assertTrue(metadata_updated)
        self.assertTrue(search_assets_changed)
        self.assertEqual(lib_files["clip.mp4"]["asset_state"], "sync_failed")
        mock_sync_lance.assert_called_once()

    @patch("src.services.indexing_service._safe_delete_unreferenced_video_data")
    @patch("src.services.indexing_service._ensure_video_chunks", return_value=([{"start": 0}], True, {"algo": 1}))
    @patch("src.services.indexing_service._sync_video_vectors_to_lance", return_value=True)
    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile", "index_dir": "index", "vector_dir": "vector"})
    @patch("src.services.indexing_service._resolve_reusable_cached_vectors")
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    def test_process_single_video_rekeys_lance_id_after_successful_reuse_sync(
        self,
        _mock_stream,
        _mock_getmtime,
        mock_reuse,
        _mock_model_dirs,
        mock_sync_lance,
        mock_chunks,
        mock_safe_delete,
    ):
        vectors = np.array([[1.0, 0.0]], dtype=np.float32)
        timestamps = np.array([0.0], dtype=np.float32)
        mock_reuse.return_value = {
            "canonical_vid": "vid_new",
            "disk_vid": "vid_old",
            "vectors": vectors,
            "timestamps": timestamps,
        }
        lib_files = {"clip.mp4": {"vid": "vid_old", "mod_time": 100.0}}

        reused_vectors, _timestamps, metadata_updated, _changed = indexing_service.process_single_video(
            "D:\\videos\\clip.mp4",
            "clip.mp4",
            lib_files,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: "vid_new",
        )

        self.assertEqual(reused_vectors.tolist(), vectors.tolist())
        self.assertTrue(metadata_updated)
        self.assertEqual(lib_files["clip.mp4"]["asset_state"], "ready")
        self.assertEqual(lib_files["clip.mp4"]["vid"], "vid_new")
        mock_chunks.assert_called_once()
        self.assertEqual(mock_chunks.call_args.args[0], "vid_old")
        mock_sync_lance.assert_called_once()
        self.assertEqual(mock_sync_lance.call_args.args[0], "vid_new")
        self.assertIsNotNone(mock_sync_lance.call_args.kwargs.get("chunks"))
        mock_safe_delete.assert_called_once()
        self.assertEqual(mock_safe_delete.call_args.args[1], "vid_old")

    @patch("src.services.indexing_service._sync_video_vectors_to_lance")
    @patch("src.services.indexing_service._try_reuse_lance_indexed_video", return_value={"canonical_vid": "vid_a"})
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    def test_process_single_video_fast_lance_reuse_skips_upsert(
        self,
        _mock_stream,
        _mock_getmtime,
        _mock_fast_reuse,
        mock_sync_lance,
    ):
        lib_files = {"clip.mp4": {"vid": "vid_a", "mod_time": 123.0, "asset_state": "ready"}}

        result = indexing_service.process_single_video(
            "D:\\videos\\clip.mp4",
            "clip.mp4",
            lib_files,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: "vid_a",
        )

        self.assertIs(result[0], indexing_service._SKIP_VIDEO_ALREADY_INDEXED)
        self.assertEqual(lib_files["clip.mp4"]["asset_state"], "ready")
        mock_sync_lance.assert_not_called()

    @patch("src.services.indexing_service.build_chunk_config", return_value={})
    @patch("src.services.indexing_service.assess_index_timestamp_health", return_value={})
    @patch("src.services.indexing_service._sync_video_vectors_to_lance", return_value=False)
    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile", "index_dir": "index", "vector_dir": "vector"})
    @patch(
        "src.services.indexing_service.generate_vectors_and_index_for_video",
        return_value=(np.array([[1.0, 0.0]], dtype=np.float32), np.array([0.0], dtype=np.float32), None, []),
    )
    @patch("src.services.indexing_service.get_legacy_video_hash", return_value="")
    @patch("src.services.indexing_service.get_video_hash", return_value="vid_a")
    @patch("src.services.indexing_service._resolve_reusable_cached_vectors", return_value=None)
    @patch("src.services.indexing_service._try_reuse_lance_indexed_video", return_value=None)
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    def test_process_single_video_marks_sync_failed_when_full_index_lance_sync_fails(
        self,
        _mock_stream,
        _mock_getmtime,
        _mock_fast,
        _mock_reuse,
        _mock_video_hash,
        _mock_legacy,
        _mock_generate,
        _mock_model_dirs,
        mock_sync_lance,
        _mock_health,
        _mock_chunk_cfg,
    ):
        lib_files = {}

        vectors, timestamps, metadata_updated, search_assets_changed = indexing_service.process_single_video(
            "D:\\videos\\clip.mp4",
            "clip.mp4",
            lib_files,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: "vid_a",
        )

        self.assertIsNone(vectors)
        self.assertIsNone(timestamps)
        self.assertTrue(metadata_updated)
        self.assertFalse(search_assets_changed)
        self.assertEqual(lib_files["clip.mp4"]["asset_state"], "sync_failed")
        mock_sync_lance.assert_called_once()

    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile", "index_dir": "index", "vector_dir": "vector"})
    @patch(
        "src.services.indexing_service.generate_vectors_and_index_for_video",
        return_value=(np.array([[1.0]], dtype=np.float32), [0.0, 1.0], None, []),
    )
    @patch("src.services.indexing_service.get_legacy_video_hash", return_value="")
    @patch("src.services.indexing_service.get_video_hash", return_value="vid_a")
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    def test_process_single_video_marks_sync_failed_when_vector_timestamp_counts_mismatch(
        self,
        _mock_stream,
        _mock_getmtime,
        _mock_video_hash,
        _mock_legacy_hash,
        _mock_generate,
        _mock_model_dirs,
    ):
        lib_files = {}

        vectors, timestamps, metadata_updated, search_assets_changed = indexing_service.process_single_video(
            "D:\\videos\\clip.mp4",
            "clip.mp4",
            lib_files,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: "vid_a",
        )

        self.assertIsNone(vectors)
        self.assertIsNone(timestamps)
        self.assertTrue(metadata_updated)
        self.assertFalse(search_assets_changed)
        self.assertEqual(lib_files["clip.mp4"]["asset_state"], "sync_failed")
        self.assertEqual(lib_files["clip.mp4"]["sync_failure_reason"], "vector_timestamp_mismatch")

    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile", "index_dir": "index", "vector_dir": "vector"})
    @patch(
        "src.services.indexing_service.generate_vectors_and_index_for_video",
        side_effect=RuntimeError("DirectML device lost: GPU out of memory"),
    )
    @patch("src.services.indexing_service.get_legacy_video_hash", return_value="")
    @patch("src.services.indexing_service.get_video_hash", return_value="vid_a")
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    def test_process_single_video_classifies_gpu_oom_exception(
        self,
        _mock_stream,
        _mock_getmtime,
        _mock_video_hash,
        _mock_legacy_hash,
        _mock_generate,
        _mock_model_dirs,
    ):
        lib_files = {}
        issues = []

        vectors, timestamps, metadata_updated, search_assets_changed = indexing_service.process_single_video(
            "D:\\videos\\clip.mp4",
            "clip.mp4",
            lib_files,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: "vid_a",
            library_path="D:\\videos",
            issue_callback=issues.append,
        )

        self.assertIsNone(vectors)
        self.assertIsNone(timestamps)
        self.assertTrue(metadata_updated)
        self.assertFalse(search_assets_changed)
        self.assertEqual(lib_files["clip.mp4"]["sync_failure_reason"], "gpu_out_of_memory")
        self.assertEqual(issues[0]["reason"], "gpu_out_of_memory")
        self.assertIn("GPU out of memory", issues[0]["detail"])

    def test_classify_sync_failure_reason_uses_system_oom_for_generic_memoryerror(self):
        reason = indexing_service._classify_sync_failure_reason(
            "D:\\videos\\clip.mp4",
            None,
            None,
            exc=MemoryError("Unable to allocate 268435456 bytes"),
        )

        self.assertEqual(reason, "system_out_of_memory")

    @patch.dict("src.services.indexing_service.os.environ", {"VIDEOSEEK_DEBUG_FORCE_GPU_OOM": "1"}, clear=False)
    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile", "index_dir": "index", "vector_dir": "vector"})
    @patch("src.services.indexing_service.get_legacy_video_hash", return_value="")
    @patch("src.services.indexing_service.get_video_hash", return_value="vid_a")
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    def test_process_single_video_supports_debug_forced_gpu_oom(
        self,
        _mock_stream,
        _mock_getmtime,
        _mock_video_hash,
        _mock_legacy_hash,
        _mock_model_dirs,
    ):
        lib_files = {}
        issues = []

        vectors, timestamps, metadata_updated, search_assets_changed = indexing_service.process_single_video(
            "D:\\videos\\clip.mp4",
            "clip.mp4",
            lib_files,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: "vid_a",
            library_path="D:\\videos",
            issue_callback=issues.append,
        )

        self.assertIsNone(vectors)
        self.assertIsNone(timestamps)
        self.assertTrue(metadata_updated)
        self.assertFalse(search_assets_changed)
        self.assertEqual(lib_files["clip.mp4"]["sync_failure_reason"], "gpu_out_of_memory")
        self.assertEqual(issues[0]["reason"], "gpu_out_of_memory")
        self.assertIn("debug injection", issues[0]["detail"].lower())

    @patch.dict("src.services.indexing_service.os.environ", {"VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM": "1"}, clear=False)
    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile", "index_dir": "index", "vector_dir": "vector"})
    @patch("src.services.indexing_service.get_legacy_video_hash", return_value="")
    @patch("src.services.indexing_service.get_video_hash", return_value="vid_a")
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    def test_process_single_video_supports_debug_forced_system_oom(
        self,
        _mock_stream,
        _mock_getmtime,
        _mock_video_hash,
        _mock_legacy_hash,
        _mock_model_dirs,
    ):
        lib_files = {}
        issues = []

        vectors, timestamps, metadata_updated, search_assets_changed = indexing_service.process_single_video(
            "D:\\videos\\clip.mp4",
            "clip.mp4",
            lib_files,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda _path: "vid_a",
            library_path="D:\\videos",
            issue_callback=issues.append,
        )

        self.assertIsNone(vectors)
        self.assertIsNone(timestamps)
        self.assertTrue(metadata_updated)
        self.assertFalse(search_assets_changed)
        self.assertEqual(lib_files["clip.mp4"]["sync_failure_reason"], "system_out_of_memory")
        self.assertEqual(issues[0]["reason"], "system_out_of_memory")
        self.assertIn("debug injection", issues[0]["detail"].lower())

    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    @patch("src.services.indexing_service.get_legacy_video_hash", return_value="")
    @patch("src.services.indexing_service.get_video_hash", return_value="vid_a")
    @patch("src.services.indexing_service.discover_video_files", return_value=["D:\\videos\\new\\clip.mp4"])
    @patch("src.services.indexing_service.os.path.exists")
    def test_reconcile_library_file_paths_updates_relocated_entry(
        self,
        mock_exists,
        _mock_discover,
        _mock_video_hash,
        _mock_legacy_hash,
        _mock_valid_source,
    ):
        root_path = "D:\\videos"
        lib_files = {
            "old\\clip.mp4": {"vid": "vid_a", "asset_state": "ready", "mod_time": 100.0},
        }

        def fake_exists(path):
            normalized = str(path).replace("\\", "/")
            if normalized == "D:/videos/new/clip.mp4":
                return True
            if normalized == "D:/videos/old/clip.mp4":
                return False
            return normalized == "D:/videos"

        mock_exists.side_effect = fake_exists

        reconciled = indexing_service.reconcile_library_file_paths(root_path, lib_files)

        self.assertEqual(reconciled, 1)
        self.assertNotIn("old\\clip.mp4", lib_files)
        self.assertNotIn("old/clip.mp4", lib_files)
        self.assertIn("new/clip.mp4", lib_files)
        self.assertEqual(lib_files["new/clip.mp4"]["vid"], "vid_a")

    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    @patch("src.services.indexing_service.get_legacy_video_hash", return_value="")
    @patch("src.services.indexing_service.get_video_hash", return_value="vid_new")
    @patch("src.services.indexing_service.discover_video_files", return_value=["D:\\videos\\new\\clip.mp4"])
    @patch("src.services.indexing_service.os.path.exists")
    def test_reconcile_library_file_paths_skips_conflicting_existing_entry(
        self,
        mock_exists,
        _mock_discover,
        _mock_video_hash,
        _mock_legacy_hash,
        _mock_valid_source,
    ):
        root_path = "D:\\videos"
        lib_files = {
            "old\\clip.mp4": {"vid": "vid_a", "asset_state": "ready"},
            "new\\clip.mp4": {"vid": "vid_new", "asset_state": "ready"},
        }

        def fake_exists(path):
            normalized = str(path).replace("\\", "/")
            if normalized.endswith("/new/clip.mp4"):
                return True
            if normalized.endswith("/old/clip.mp4"):
                return False
            return normalized == "D:/videos"

        mock_exists.side_effect = fake_exists

        reconciled = indexing_service.reconcile_library_file_paths(root_path, lib_files)

        self.assertEqual(reconciled, 0)
        self.assertIn("old\\clip.mp4", lib_files)
        self.assertEqual(lib_files["new\\clip.mp4"]["vid"], "vid_new")

    def test_filter_index_problem_issues_excludes_path_reconcile(self):
        issues = [
            {"reason": "path_reconciled", "action": "relocated"},
            {"reason": "gpu_out_of_memory", "action": "skipped"},
        ]
        filtered = indexing_service.filter_index_problem_issues(issues)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["reason"], "gpu_out_of_memory")

    @patch("src.services.indexing_service.load_video_chunks_by_id", return_value=[])
    @patch("src.services.indexing_service.process_single_video")
    @patch("src.services.indexing_service.cleanup_invalid_library_files", return_value=iter(()))
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    @patch("src.services.indexing_service.get_legacy_video_hash", return_value="")
    @patch("src.services.indexing_service.get_video_hash", return_value="vid_a")
    @patch("src.services.indexing_service.discover_video_files", return_value=["D:\\videos\\new\\clip.mp4"])
    @patch("src.services.indexing_service.os.path.exists")
    def test_scan_target_libraries_persists_meta_after_path_reconcile(
        self,
        mock_exists,
        _mock_discover,
        _mock_video_hash,
        _mock_legacy_hash,
        _mock_valid_source,
        _mock_cleanup_invalid,
        mock_process_single_video,
        _mock_load_chunks,
    ):
        root_path = "D:\\videos"
        meta = {
            "libraries": {
                root_path: {
                    "files": {
                        "old\\clip.mp4": {"vid": "vid_a", "asset_state": "ready"},
                    }
                }
            }
        }
        persist_calls = []
        mock_process_single_video.return_value = (np.array([[1.0]], dtype=np.float32), [0.0], True, False)

        def fake_exists(path):
            normalized = str(path).replace("\\", "/")
            if normalized == "D:/videos/new/clip.mp4":
                return True
            if normalized == "D:/videos/old/clip.mp4":
                return False
            return normalized == "D:/videos"

        mock_exists.side_effect = fake_exists

        indexing_service.scan_target_libraries(
            meta,
            {},
            lambda path: "vid_a",
            persist_meta_callback=lambda: persist_calls.append("saved"),
        )

        lib_files = meta["libraries"][root_path]["files"]
        self.assertNotIn("old\\clip.mp4", lib_files)
        self.assertNotIn("old/clip.mp4", lib_files)
        self.assertIn("new/clip.mp4", lib_files)
        self.assertEqual(persist_calls, ["saved"])

    @patch("src.services.indexing_service.load_video_chunks_by_id", return_value=[])
    @patch("src.services.indexing_service.process_single_video")
    @patch("src.services.indexing_service.reconcile_library_file_paths", return_value=0)
    @patch("src.services.indexing_service.cleanup_invalid_library_files", return_value=iter(()))
    @patch("src.services.indexing_service.discover_video_files", return_value=["D:\\videos\\clip.mp4"])
    @patch("src.services.indexing_service.os.path.exists", return_value=True)
    def test_scan_target_libraries_persists_meta_after_new_video(
        self,
        _mock_exists,
        _mock_discover,
        _mock_cleanup_invalid,
        _mock_reconcile,
        mock_process_single_video,
        _mock_load_chunks,
    ):
        meta = {"libraries": {"D:\\videos": {"files": {}}}}
        persist_calls = []
        mock_process_single_video.return_value = (np.array([[1.0]], dtype=np.float32), [0.0], True, True)

        indexing_service.scan_target_libraries(
            meta,
            {},
            lambda path: "vid_a",
            persist_meta_callback=lambda: persist_calls.append("saved"),
        )

        self.assertEqual(persist_calls, ["saved"])

    @patch("src.services.indexing_service.load_video_chunks_by_id", return_value=[])
    @patch("src.services.indexing_service.process_single_video", return_value=(None, None, True, False))
    @patch("src.services.indexing_service.cleanup_invalid_library_files", return_value=iter(()))
    @patch("src.services.indexing_service.discover_video_files", return_value=["D:\\videos\\clip.mp4"])
    @patch("src.services.indexing_service.os.path.exists", return_value=True)
    def test_scan_target_libraries_collects_failed_videos(
        self,
        _mock_exists,
        _mock_discover,
        _mock_cleanup_invalid,
        _mock_process_single_video,
        _mock_load_chunks,
    ):
        meta = {"libraries": {"D:\\videos": {"files": {}}}}
        persist_calls = []

        result = indexing_service.scan_target_libraries(
            meta,
            {},
            lambda path: "vid_a",
            persist_meta_callback=lambda: persist_calls.append("saved"),
        )

        self.assertEqual(result[0], ["D:\\videos\\clip.mp4"])
        self.assertFalse(result[1])
        self.assertEqual(persist_calls, ["saved"])

    @patch("src.services.indexing_service.load_video_chunks_by_id", return_value=[])
    @patch("src.services.indexing_service.process_single_video")
    @patch("src.services.indexing_service.cleanup_invalid_library_files", return_value=iter(()))
    @patch("src.services.indexing_service.discover_video_files", return_value=["D:\\videos\\clip.mp4"])
    @patch("src.services.indexing_service.os.path.exists", return_value=True)
    def test_scan_target_libraries_marks_failed_videos_without_collecting_vectors(
        self,
        _mock_exists,
        _mock_discover,
        _mock_cleanup_invalid,
        mock_process_single_video,
        _mock_load_chunks,
    ):
        mock_process_single_video.return_value = (None, None, True, False)
        meta = {"libraries": {"D:\\videos": {"files": {}}}}

        failed_videos, search_assets_changed = indexing_service.scan_target_libraries(
            meta,
            {},
            lambda path: "vid_a",
            include_existing_assets=True,
        )

        self.assertEqual(failed_videos, ["D:\\videos\\clip.mp4"])
        self.assertFalse(search_assets_changed)

    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"base_dir": "profile", "index_dir": "index", "vector_dir": "vector"})
    @patch("src.services.indexing_service.os.remove")
    @patch("src.services.indexing_service.os.path.exists")
    @patch("src.services.indexing_service.load_video_chunks_by_id", return_value=[])
    @patch("src.services.indexing_service.process_single_video")
    @patch("src.services.indexing_service.cleanup_invalid_library_files", return_value=iter(["vid_bad"]))
    @patch("src.services.indexing_service.discover_video_files", return_value=[])
    def test_scan_target_libraries_removes_assets_for_invalid_existing_entries(
        self,
        _mock_discover,
        _mock_cleanup_invalid,
        mock_process_single_video,
        _mock_load_chunks,
        mock_exists,
        mock_remove,
        _mock_get_model_dirs,
    ):
        meta = {"libraries": {"D:\\videos": {"files": {}}}}
        persist_calls = []

        def fake_exists(path):
            return str(path).endswith("vid_bad_vectors.npy") or str(path).endswith("vid_bad_index.faiss") or path == "D:\\videos"

        mock_exists.side_effect = fake_exists

        indexing_service.scan_target_libraries(
            meta,
            {"index_dir": "index", "vector_dir": "vector"},
            lambda path: "vid_a",
            persist_meta_callback=lambda: persist_calls.append("saved"),
        )

        mock_process_single_video.assert_not_called()
        self.assertEqual(mock_remove.call_count, 2)
        self.assertEqual(persist_calls, ["saved"])

    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], False))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", side_effect=AssertionError("should not cleanup"))
    @patch("src.workflows.update_video.load_model_metadata", return_value={"libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid", "asset_state": "ready"}}}}})
    @patch("src.workflows.update_video.load_config")
    @patch("src.workflows.update_video.garbage_collect_indices")
    @patch("src.workflows.update_video.os.path.exists", return_value=True)
    def test_update_videos_flow_skips_cleanup_when_auto_cleanup_disabled(
        self,
        _mock_exists,
        _mock_gc,
        mock_load_config,
        mock_load_meta,
        _mock_cleanup,
        _mock_save_meta,
        _mock_scan,
    ):
        mock_load_config.return_value = {
            "auto_cleanup_missing_files": False,
            "meta_file": "source/meta.json",
        }

        output = update_video.update_videos_flow()

        self.assertIsNotNone(output[0])
        saved_meta = mock_load_meta.return_value
        self.assertEqual(saved_meta["libraries"]["D:\\videos"]["index_state"], "ready")

    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], False))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", return_value=iter(()))
    @patch("src.workflows.update_video.load_model_metadata", return_value={"libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid", "asset_state": "ready"}}}}})
    @patch("src.workflows.update_video.load_config")
    @patch("src.workflows.update_video.garbage_collect_indices")
    def test_update_videos_flow_passes_issue_callback_to_scan(
        self,
        _mock_gc,
        mock_load_config,
        _mock_load_meta,
        _mock_cleanup,
        _mock_save_meta,
        mock_scan,
    ):
        mock_load_config.return_value = {
            "auto_cleanup_missing_files": False,
            "meta_file": "source/meta.json",
        }
        issues = []

        output = update_video.update_videos_flow(issue_callback=issues.append)

        self.assertIsNotNone(output[0])
        self.assertTrue(callable(mock_scan.call_args.kwargs["issue_callback"]))

    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], True))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", return_value=iter(()))
    @patch(
        "src.workflows.update_video.load_model_metadata",
        return_value={
            "search_index_schema_version": 2,
            "libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid", "asset_state": "ready"}}}},
        },
    )
    @patch("src.workflows.update_video.load_config")
    @patch("src.workflows.update_video.garbage_collect_indices")
    def test_update_videos_flow_profile_mode_finalizes_library_state(
        self,
        _mock_gc,
        mock_load_config,
        _mock_load_meta,
        _mock_cleanup,
        _mock_save_meta,
        mock_scan,
    ):
        mock_load_config.return_value = {
            "auto_cleanup_missing_files": False,
            "meta_file": "source/meta.json",
        }

        output = update_video.update_videos_flow(
            target_lib="D:\\videos",
            include_existing_assets=False,
            rebuild_global_assets=False,
        )

        self.assertIsNotNone(output[0])
        self.assertEqual(mock_scan.call_args.kwargs["include_existing_assets"], False)

    @patch("src.workflows.update_video.os.path.exists")
    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], False))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", side_effect=AssertionError("should not cleanup"))
    @patch(
        "src.workflows.update_video.load_model_metadata",
        return_value={
            "libraries": {
                "D:\\videos": {
                    "files": {
                        "missing.mp4": {"vid": "vid_missing", "asset_state": "ready"},
                    }
                }
            }
        },
    )
    @patch("src.workflows.update_video.load_config")
    @patch("src.workflows.update_video.garbage_collect_indices")
    def test_update_videos_flow_marks_missing_source_when_cleanup_disabled(
        self,
        _mock_gc,
        mock_load_config,
        mock_load_meta,
        _mock_cleanup,
        _mock_save_meta,
        _mock_scan,
        mock_exists,
    ):
        mock_load_config.return_value = {
            "auto_cleanup_missing_files": False,
            "meta_file": "source/meta.json",
        }

        def fake_exists(path):
            normalized = str(path).replace("/", "\\")
            if normalized == "D:\\videos":
                return True
            if normalized == "D:\\videos\\missing.mp4":
                return False
            return True

        mock_exists.side_effect = fake_exists

        output = update_video.update_videos_flow()

        self.assertIsNone(output[0])
        saved_meta = mock_load_meta.return_value
        self.assertEqual(saved_meta["libraries"]["D:\\videos"]["files"]["missing.mp4"]["asset_state"], "missing_source")

    @patch("src.workflows.update_video.delete_physical_video_data")
    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], True))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", return_value=iter(["vid_a"]))
    @patch("src.workflows.update_video.load_model_metadata", return_value={"libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid", "asset_state": "ready"}}}}})
    @patch("src.workflows.update_video.load_config")
    @patch("src.workflows.update_video.garbage_collect_indices")
    def test_update_videos_flow_forces_cleanup_when_requested(
        self,
        _mock_gc,
        mock_load_config,
        _mock_load_meta,
        mock_cleanup,
        _mock_save_meta,
        _mock_scan,
        mock_delete_video_data,
    ):
        mock_load_config.return_value = {
            "auto_cleanup_missing_files": False,
            "meta_file": "source/meta.json",
        }

        output = update_video.update_videos_flow(force_cleanup_missing_files=True)

        self.assertIsNotNone(output[0])
        mock_cleanup.assert_called_once()
        mock_delete_video_data.assert_called_once_with("vid_a", mock_load_config.return_value)

    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], True))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", return_value=iter(["vid_a"]))
    @patch("src.workflows.update_video.load_model_metadata", return_value={"libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid", "asset_state": "ready"}}}}})
    @patch("src.workflows.update_video.load_config")
    @patch("src.workflows.update_video.garbage_collect_indices")
    @patch("src.workflows.update_video.delete_physical_video_data")
    def test_update_videos_flow_passes_selected_missing_entries_to_cleanup(
        self,
        mock_delete_video_data,
        _mock_gc,
        mock_load_config,
        _mock_load_meta,
        mock_cleanup,
        _mock_save_meta,
        _mock_scan,
    ):
        selected_entries = [{"library_path": "D:\\videos", "video_rel_path": "missing.mp4"}]
        mock_load_config.return_value = {
            "auto_cleanup_missing_files": False,
            "meta_file": "source/meta.json",
        }

        output = update_video.update_videos_flow(
            force_cleanup_missing_files=True,
            cleanup_missing_entries=selected_entries,
        )

        self.assertIsNotNone(output[0])
        self.assertEqual(mock_cleanup.call_args.kwargs["selected_entries"], selected_entries)
        mock_delete_video_data.assert_called_once()

    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.load_model_metadata", return_value={"libraries": {"D:\\videos": {"files": {}}}})
    @patch("src.workflows.update_video.load_config", return_value={"auto_cleanup_missing_files": False, "meta_file": "source/meta.json"})
    @patch("src.workflows.update_video.garbage_collect_indices")
    @patch("src.workflows.update_video.scan_target_libraries", side_effect=RuntimeError("interrupted"))
    @patch("src.workflows.update_video.os.path.exists", return_value=True)
    def test_update_videos_flow_keeps_partial_state_on_interruption(
        self,
        _mock_exists,
        _mock_scan,
        _mock_gc,
        _mock_load_config,
        mock_load_meta,
        mock_save_meta,
    ):
        mock_load_meta.return_value["libraries"]["D:\\videos"]["index_state"] = "ready"
        with self.assertRaises(RuntimeError):
            update_video.update_videos_flow()

        saved_meta = mock_load_meta.return_value
        self.assertEqual(saved_meta["libraries"]["D:\\videos"]["index_state"], "ready")
        self.assertFalse(mock_save_meta.called)

    @patch("src.workflows.update_video.save_model_metadata")
    @patch(
        "src.workflows.update_video.load_model_metadata",
        return_value={
            "libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid"}}}},
        },
    )
    @patch("src.workflows.update_video.load_config", return_value={"auto_cleanup_missing_files": False, "meta_file": "source/meta.json"})
    @patch("src.workflows.update_video.garbage_collect_indices")
    @patch(
        "src.workflows.update_video.scan_target_libraries",
        side_effect=update_video.IndexUpdateInterrupted("stopped", search_assets_changed=True),
    )
    def test_update_videos_flow_persists_meta_on_interrupted_partial_asset_change(
        self,
        _mock_scan,
        _mock_gc,
        _mock_load_config,
        mock_load_meta,
        mock_save_meta,
    ):
        with self.assertRaises(update_video.IndexUpdateInterrupted):
            update_video.update_videos_flow(target_lib="D:\\videos", rebuild_global_assets=False)

        self.assertTrue(mock_save_meta.called)




if __name__ == "__main__":
    unittest.main()
