import tempfile
import unittest
import os
import zipfile
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import sys
import types

try:
    import cv2 as _real_cv2
except Exception:
    _real_cv2 = None

if _real_cv2 is not None:
    sys.modules["cv2"] = _real_cv2
else:
    cv2_module = sys.modules.setdefault("cv2", types.SimpleNamespace())
    cv2_module.VideoCapture = getattr(cv2_module, "VideoCapture", lambda *_args, **_kwargs: None)
    cv2_module.CAP_PROP_FRAME_COUNT = getattr(cv2_module, "CAP_PROP_FRAME_COUNT", 7)
    cv2_module.CAP_PROP_POS_MSEC = getattr(cv2_module, "CAP_PROP_POS_MSEC", 0)
    cv2_module.CAP_PROP_FPS = getattr(cv2_module, "CAP_PROP_FPS", 5)

faiss_module = sys.modules.setdefault("faiss", types.SimpleNamespace())
faiss_module.normalize_L2 = getattr(faiss_module, "normalize_L2", lambda *_args, **_kwargs: None)

from src.domain.remote_search_hit import RemoteSearchHit
from src.domain.search_hit import SearchHit
from src.services import model_service
from src.services import remote_search_service
from src.services import indexing_service, search_service
from src.services import library_service, remote_library_service
from src.services import model_package_service
from src.workflows import update_video
from src import utils


def _model_dirs_from_test_config(config=None):
    cfg = dict(config or {})
    return {
        "vector_dir": cfg.get("vector_dir", "source/vector"),
        "index_dir": cfg.get("index_dir", "source/index"),
    }


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
    def test_remove_library_marks_global_index_stale(
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
        self.assertEqual(mock_load_meta.return_value["global_index_state"], library_service.GLOBAL_INDEX_STATE_STALE)
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
                    "detail": "Unreadable or unsupported video stream.",
                }
            ],
        )

    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"index_dir": "index", "vector_dir": "vector"})
    @patch("src.services.indexing_service.get_video_duration_seconds", return_value=60.0)
    @patch("src.services.indexing_service.generate_vectors_and_index_for_video", return_value=([], [], None))
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

    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"index_dir": "index", "vector_dir": "vector"})
    @patch("src.services.indexing_service.get_video_duration_seconds", return_value=0.6)
    @patch("src.services.indexing_service.generate_vectors_and_index_for_video", return_value=([], [], None))
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

    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"index_dir": "index", "vector_dir": "vector"})
    @patch("src.services.indexing_service.create_clip_index")
    @patch("src.services.indexing_service._resolve_reusable_cached_vectors")
    @patch("src.services.indexing_service.os.path.getmtime", return_value=123.0)
    @patch("src.services.indexing_service._is_valid_video_source", return_value=True)
    def test_process_single_video_rebuilds_missing_per_video_index_when_reusing_vectors(
        self,
        _mock_stream,
        _mock_getmtime,
        mock_reuse,
        mock_create_index,
        _mock_model_dirs,
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
        mock_create_index.assert_called_once()
        self.assertEqual(mock_create_index.call_args.args[1], "index\\vid_a_index.faiss")

    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"index_dir": "index", "vector_dir": "vector"})
    @patch(
        "src.services.indexing_service.generate_vectors_and_index_for_video",
        return_value=(np.array([[1.0]], dtype=np.float32), [0.0, 1.0], None),
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

    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"index_dir": "index", "vector_dir": "vector"})
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
    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"index_dir": "index", "vector_dir": "vector"})
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
    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"index_dir": "index", "vector_dir": "vector"})
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

    @patch("src.services.indexing_service.load_video_chunks_by_id", return_value=[])
    @patch("src.services.indexing_service.process_single_video")
    @patch("src.services.indexing_service.cleanup_invalid_library_files", return_value=iter(()))
    @patch("src.services.indexing_service.discover_video_files", return_value=["D:\\videos\\clip.mp4"])
    @patch("src.services.indexing_service.os.path.exists", return_value=True)
    def test_scan_target_libraries_persists_meta_after_new_video(
        self,
        _mock_exists,
        _mock_discover,
        _mock_cleanup_invalid,
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

    @patch("src.services.indexing_service.get_local_model_asset_dirs", return_value={"index_dir": "index", "vector_dir": "vector"})
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

    @patch("src.services.indexing_service.load_clip_index", return_value=object())
    @patch("src.services.indexing_service._save_global_chunk_metadata")
    @patch("src.services.indexing_service._save_global_frame_metadata")
    @patch("src.services.indexing_service.IncrementalClipIndex")
    @patch("src.services.indexing_service.get_global_model_asset_paths")
    @patch("src.services.indexing_service.ensure_folder_exists")
    @patch(
        "src.services.indexing_service.iter_ready_library_chunk_sources",
        return_value=iter([]),
    )
    @patch("src.services.indexing_service.iter_ready_library_frame_sources")
    def test_build_global_index_merges_videos_incrementally(
        self,
        mock_iter_frames,
        _mock_iter_chunks,
        _mock_ensure,
        mock_global_paths,
        mock_incremental_cls,
        _mock_save_frame_meta,
        _mock_save_chunk_meta,
        _mock_load_index,
    ):
        vectors_a = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        vectors_b = np.array([[1.0, 1.0]], dtype=np.float32)
        mock_iter_frames.return_value = iter(
            [
                (vectors_a, [0.0, 1.0], "D:/a.mp4"),
                (vectors_b, [2.0], "D:/b.mp4"),
            ]
        )
        mock_global_paths.return_value = {
            "cross_index_file": "global/cross.faiss",
            "cross_vector_file": "global/cross.npy",
            "cross_chunk_index_file": "global/chunk.faiss",
            "cross_chunk_vector_file": "global/chunk.npy",
        }
        frame_builder = MagicMock()
        frame_builder.total = 3
        chunk_builder = MagicMock()
        chunk_builder.total = 0
        mock_incremental_cls.side_effect = [frame_builder, chunk_builder]

        meta = {"libraries": {"D:/lib": {"files": {"a.mp4": {"vid": "a", "asset_state": "ready"}}}}}
        result = indexing_service.build_global_index(meta, {})

        self.assertIsNotNone(result)
        self.assertEqual(frame_builder.add.call_count, 2)
        frame_builder.save.assert_called_once_with("global/cross.faiss")
        _mock_save_frame_meta.assert_called_once()

    @patch("src.workflows.update_video.build_global_index", return_value=(np.array([0.0]), np.array(["a.mp4"]), object()))
    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], False))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", side_effect=AssertionError("should not cleanup"))
    @patch("src.workflows.update_video.load_model_metadata", return_value={"libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid"}}}}})
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
        mock_build,
    ):
        mock_load_config.return_value = {
            "auto_cleanup_missing_files": False,
            "meta_file": "source/meta.json",
        }

        output = update_video.update_videos_flow()

        self.assertIsNotNone(output[0])
        mock_build.assert_called_once()
        saved_meta = mock_load_meta.return_value
        self.assertEqual(saved_meta["libraries"]["D:\\videos"]["index_state"], "ready")

    @patch("src.workflows.update_video.build_global_index", return_value=(np.array([0.0]), np.array(["a.mp4"]), object()))
    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], False))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", return_value=iter(()))
    @patch("src.workflows.update_video.load_model_metadata", return_value={"libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid"}}}}})
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
        _mock_build,
    ):
        mock_load_config.return_value = {
            "auto_cleanup_missing_files": False,
            "meta_file": "source/meta.json",
        }
        issues = []

        output = update_video.update_videos_flow(issue_callback=issues.append)

        self.assertIsNotNone(output[0])
        self.assertTrue(callable(mock_scan.call_args.kwargs["issue_callback"]))

    @patch("src.workflows.update_video.build_library_search_indexes")
    @patch("src.workflows.update_video.build_global_index")
    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], True))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", return_value=iter(()))
    @patch(
        "src.workflows.update_video.load_model_metadata",
        return_value={
            "search_index_schema_version": 2,
            "libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid"}}}},
            "global_index_state": library_service.GLOBAL_INDEX_STATE_STALE,
        },
    )
    @patch("src.workflows.update_video.load_config")
    @patch("src.workflows.update_video.garbage_collect_indices")
    def test_update_videos_flow_profile_mode_rebuilds_library_index_when_v2(
        self,
        _mock_gc,
        mock_load_config,
        _mock_load_meta,
        _mock_cleanup,
        _mock_save_meta,
        mock_scan,
        mock_build_global,
        mock_build_library_indexes,
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

        self.assertEqual(output, (None, None, None, None))
        mock_build_global.assert_not_called()
        mock_build_library_indexes.assert_called_once()

    @patch("src.workflows.update_video.build_global_index")
    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], True))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", return_value=iter(()))
    @patch(
        "src.workflows.update_video.load_model_metadata",
        return_value={
            "libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid"}}}},
            "global_index_state": library_service.GLOBAL_INDEX_STATE_STALE,
        },
    )
    @patch("src.workflows.update_video.load_config")
    @patch("src.workflows.update_video.garbage_collect_indices")
    def test_update_videos_flow_profile_mode_skips_global_rebuild_and_existing_assets(
        self,
        _mock_gc,
        mock_load_config,
        _mock_load_meta,
        _mock_cleanup,
        _mock_save_meta,
        mock_scan,
        mock_build_global,
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

        self.assertEqual(output, (None, None, None, None))
        self.assertEqual(mock_scan.call_args.kwargs["include_existing_assets"], False)
        mock_build_global.assert_not_called()
        self.assertEqual(_mock_load_meta.return_value["global_index_state"], library_service.GLOBAL_INDEX_STATE_STALE)

    @patch("src.workflows.update_video.os.path.exists")
    @patch("src.workflows.update_video.build_global_index", return_value=(np.array([0.0]), np.array(["a.mp4"]), object()))
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
        mock_build,
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

        self.assertIsNotNone(output[0])
        mock_build.assert_called_once()
        saved_meta = mock_load_meta.return_value
        self.assertEqual(saved_meta["libraries"]["D:\\videos"]["files"]["missing.mp4"]["asset_state"], "missing_source")

    @patch("src.workflows.update_video.build_global_index", return_value=(np.array([0.0]), np.array(["a.mp4"]), object()))
    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], True))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", return_value=iter(()))
    @patch(
        "src.workflows.update_video.load_model_metadata",
        return_value={
            "libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid"}}}},
            "global_index_state": library_service.GLOBAL_INDEX_STATE_STALE,
        },
    )
    @patch("src.workflows.update_video.load_config")
    @patch("src.workflows.update_video.garbage_collect_indices")
    def test_update_videos_flow_marks_global_index_fresh_after_global_rebuild(
        self,
        _mock_gc,
        mock_load_config,
        mock_load_meta,
        _mock_cleanup,
        _mock_save_meta,
        _mock_scan,
        mock_build,
    ):
        mock_load_config.return_value = {
            "auto_cleanup_missing_files": False,
            "meta_file": "source/meta.json",
        }

        output = update_video.update_videos_flow()

        self.assertIsNotNone(output[0])
        mock_build.assert_called_once()
        self.assertEqual(mock_load_meta.return_value["global_index_state"], library_service.GLOBAL_INDEX_STATE_FRESH)

    @patch("src.workflows.update_video.delete_physical_video_data")
    @patch("src.workflows.update_video.build_global_index", return_value=(np.array([0.0]), np.array(["a.mp4"]), object()))
    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], True))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", return_value=iter(["vid_a"]))
    @patch("src.workflows.update_video.load_model_metadata", return_value={"libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid"}}}}})
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
        mock_build,
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
        mock_build.assert_called_once()

    @patch("src.workflows.update_video.build_global_index", return_value=(np.array([0.0]), np.array(["a.mp4"]), object()))
    @patch("src.workflows.update_video.scan_target_libraries", return_value=([], True))
    @patch("src.workflows.update_video.save_model_metadata")
    @patch("src.workflows.update_video.cleanup_missing_library_files", return_value=iter(["vid_a"]))
    @patch("src.workflows.update_video.load_model_metadata", return_value={"libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid"}}}}})
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
        mock_build,
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
        mock_build.assert_called_once()

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
        with self.assertRaises(RuntimeError):
            update_video.update_videos_flow()

        saved_meta = mock_load_meta.return_value
        self.assertEqual(saved_meta["libraries"]["D:\\videos"]["index_state"], "partial")
        self.assertTrue(mock_save_meta.called)

    @patch("src.workflows.update_video.save_model_metadata")
    @patch(
        "src.workflows.update_video.load_model_metadata",
        return_value={
            "libraries": {"D:\\videos": {"files": {"a.mp4": {"vid": "vid"}}}},
            "global_index_state": library_service.GLOBAL_INDEX_STATE_FRESH,
        },
    )
    @patch("src.workflows.update_video.load_config", return_value={"auto_cleanup_missing_files": False, "meta_file": "source/meta.json"})
    @patch("src.workflows.update_video.garbage_collect_indices")
    @patch(
        "src.workflows.update_video.scan_target_libraries",
        side_effect=update_video.IndexUpdateInterrupted("stopped", search_assets_changed=True),
    )
    def test_update_videos_flow_marks_global_index_stale_on_interrupted_partial_asset_change(
        self,
        _mock_scan,
        _mock_gc,
        _mock_load_config,
        mock_load_meta,
        mock_save_meta,
    ):
        with self.assertRaises(update_video.IndexUpdateInterrupted):
            update_video.update_videos_flow(target_lib="D:\\videos", rebuild_global_assets=False)

        self.assertEqual(mock_load_meta.return_value["global_index_state"], library_service.GLOBAL_INDEX_STATE_STALE)
        self.assertTrue(mock_save_meta.called)


class SearchServiceTests(unittest.TestCase):
    @patch("src.services.search_service.faiss.normalize_L2", create=True)
    @patch("src.services.search_service.get_text_embedding")
    def test_build_query_vector_for_text(self, mock_text_embedding, mock_normalize):
        mock_text_embedding.return_value = np.array([[1.0, 2.0]], dtype=np.float32)

        result = search_service.build_query_vector("cat on sofa", is_text=True)

        self.assertEqual(result.dtype, np.float32)
        mock_normalize.assert_called_once()

    @patch("src.services.search_service.load_search_assets")
    @patch("src.services.search_service.build_query_vector")
    @patch("src.services.search_service._search_frame_results_with_ids")
    @patch("src.services.search_service.load_config")
    def test_run_search_returns_empty_when_index_missing(
        self,
        mock_load_config,
        mock_search_results_with_ids,
        mock_build_query_vector,
        mock_load_assets,
    ):
        mock_load_config.return_value = {"cross_index_file": "index.faiss", "cross_vector_file": "vectors.npy"}
        mock_load_assets.return_value = (None, None, None)

        result = search_service.run_search("query", is_text=True)

        self.assertEqual(result, [])
        mock_build_query_vector.assert_called_once()
        mock_search_results_with_ids.assert_not_called()

    @patch("src.services.search_service._run_frame_search_per_videos")
    @patch("src.services.search_service.load_config")
    def test_run_search_uses_per_video_route_when_video_scope_set(
        self,
        mock_load_config,
        mock_per_video_search,
    ):
        from src.domain.search_hit import SearchHit

        mock_load_config.return_value = {}
        expected = [SearchHit(1.0, 1.0, 0.8, "D:/clip.mp4")]
        mock_per_video_search.return_value = expected

        result = search_service.run_search(
            "query",
            is_text=True,
            top_k=5,
            scope_video_paths=["D:/clip.mp4"],
        )

        self.assertEqual(result, expected)
        mock_per_video_search.assert_called_once()

    @patch("src.services.search_service.build_query_vector", return_value=np.array([[1.0, 0.0]], dtype=np.float32))
    @patch("src.services.search_service._run_frame_search_per_videos")
    @patch("src.services.search_service.load_config")
    def test_run_search_uses_per_video_route_for_precise_scoped_image(
        self,
        mock_load_config,
        mock_per_video_search,
        _mock_build_query_vector,
    ):
        from src.domain.search_hit import SearchHit

        mock_load_config.return_value = {}
        expected = [SearchHit(12.0, 12.0, 0.91, "D:/clip.mp4")]
        mock_per_video_search.return_value = expected

        result = search_service.run_search(
            "D:/query.jpg",
            is_text=False,
            top_k=5,
            scope_video_paths=["D:/clip.mp4"],
            search_precision_mode="precise",
        )

        self.assertEqual(result, expected)
        mock_per_video_search.assert_called_once()
        self.assertTrue(mock_per_video_search.call_args.kwargs.get("precise_image"))

    @patch("src.services.search_service.get_active_model_profile")
    def test_check_asset_profile_compatibility_rejects_mismatched_model_id(self, mock_get_profile):
        mock_get_profile.return_value = {"id": "siglip2_default", "provider": "siglip2_onnx"}
        asset_info = {
            "embedding_spec": {
                "model_id": "clip_onnx_default",
                "provider": "clip_onnx",
                "embedding_space": "clip_onnx_default",
                "dimension": 512,
                "metric": "ip",
            },
            "index_dim": 512,
        }

        with self.assertRaises(RuntimeError) as ctx:
            search_service._check_asset_profile_compatibility({}, asset_info, asset_label="frame")

        self.assertIn("active profile", str(ctx.exception).lower())

    @patch("src.services.search_service.get_active_model_profile")
    def test_check_asset_profile_compatibility_ignores_missing_embedding_spec(self, mock_get_profile):
        mock_get_profile.return_value = {"id": "clip_onnx_default", "provider": "clip_onnx"}
        asset_info = {"embedding_spec": None, "index_dim": 512}

        search_service._check_asset_profile_compatibility({}, asset_info, asset_label="frame")

    def test_apply_frame_neighbor_rerank_disabled_by_default(self):
        class DummyIndex:
            def reconstruct(self, idx):
                return np.array([1.0, 0.0], dtype=np.float32)

        results = [SearchHit(1.0, 1.0, 0.8, "a.mp4")]
        frame_ids = [1]
        query_vector = np.array([[1.0, 0.0]], dtype=np.float32)
        timestamps = np.array([0.0, 1.0, 2.0], dtype=np.float32)
        paths = np.array(["a.mp4", "a.mp4", "a.mp4"], dtype=object)

        reranked = search_service._apply_frame_neighbor_rerank(
            results,
            frame_ids,
            query_vector,
            DummyIndex(),
            timestamps,
            paths,
            config={},
            is_text=True,
        )
        self.assertEqual(reranked, results)

    def test_neighbor_rerank_auto_enabled_for_image_search(self):
        self.assertFalse(search_service._neighbor_rerank_enabled({}, is_text=False, precise_image=True))
        self.assertFalse(search_service._neighbor_rerank_enabled({}, is_text=False, precise_image=False))

    def test_neighbor_rerank_respects_text_default(self):
        self.assertFalse(search_service._neighbor_rerank_enabled({}, is_text=True))

    def test_neighbor_rerank_disabled_for_fast_image_search(self):
        self.assertFalse(search_service._neighbor_rerank_enabled({}, is_text=False, precise_image=False))

    @patch("src.services.search_service.apply_image_pixel_rerank")
    def test_finalize_frame_hits_prefers_pixel_query_data(self, mock_pixel):
        mock_pixel.return_value = []
        hits = [SearchHit(1.0, 1.0, 0.9, "a.mp4")]
        search_service._finalize_frame_hits(
            "text query",
            False,
            hits,
            5,
            {},
            precise_image=True,
            pixel_query_data="/path/to/ref.jpg",
        )
        mock_pixel.assert_called_once()
        self.assertEqual(mock_pixel.call_args[0][0], "/path/to/ref.jpg")

    def test_collect_neighbor_frame_ids_uses_time_window(self):
        timestamps = np.array([10.0, 11.0, 12.0, 13.0, 20.0], dtype=np.float32)
        paths = np.array(["a.mp4"] * 4 + ["b.mp4"], dtype=object)
        ids = search_service._collect_neighbor_frame_ids(2, timestamps, paths, window_sec=1.5)
        self.assertEqual(ids, [2, 1, 3])

    def test_apply_frame_neighbor_rerank_snaps_to_better_neighbor(self):
        class DummyIndex:
            def __init__(self):
                self._vectors = {
                    0: np.array([0.6, 0.8], dtype=np.float32),
                    1: np.array([0.8, 0.2], dtype=np.float32),
                    2: np.array([1.0, 0.0], dtype=np.float32),
                }

            def reconstruct(self, idx):
                return self._vectors[idx]

        results = [SearchHit(1.0, 1.0, 0.8, "a.mp4")]
        frame_ids = [1]
        query_vector = np.array([[1.0, 0.0]], dtype=np.float32)
        timestamps = np.array([0.0, 1.0, 2.0], dtype=np.float32)
        paths = np.array(["a.mp4", "a.mp4", "a.mp4"], dtype=object)
        config = {
            "frame_neighbor_rerank_enabled": True,
            "frame_neighbor_rerank_top_n": 5,
            "frame_neighbor_rerank_window": 2,
        }

        reranked = search_service._apply_frame_neighbor_rerank(
            results,
            frame_ids,
            query_vector,
            DummyIndex(),
            timestamps,
            paths,
            config=config,
        )
        self.assertEqual(reranked[0].start_sec, 2.0)
        self.assertEqual(reranked[0].end_sec, 2.0)
        self.assertGreater(reranked[0].score, results[0].score)


class RemoteSearchServiceTests(unittest.TestCase):
    @patch("src.services.remote_search_service.load_config", return_value={"search_top_k": 20})
    @patch("src.services.remote_search_service.load_remote_search_assets", return_value=None)
    def test_run_remote_search_returns_empty_without_assets(self, _mock_assets, _mock_config):
        result = remote_search_service.run_remote_search("query", is_text=True)
        self.assertEqual(result, [])

    @patch("src.services.remote_search_service.load_config", return_value={"search_top_k": 10})
    @patch("src.services.remote_search_service.build_query_vector")
    @patch("src.services.remote_search_service.load_remote_search_assets")
    def test_run_remote_search_returns_remote_search_hits(self, mock_assets, mock_query, _mock_config):
        class DummyIndex:
            ntotal = 2

            def search(self, query_vector, actual_k):
                distances = np.array([[0.95, 0.85]], dtype=np.float32)
                indices = np.array([[0, 1]], dtype=np.int64)
                return distances, indices

        mock_query.return_value = np.zeros((1, 512), dtype=np.float32)
        mock_assets.return_value = {
            "index": DummyIndex(),
            "timestamps": np.array([12.0, 34.0], dtype=np.float32),
            "source_links": ["https://a.example", "https://b.example"],
            "titles": ["A Title", "B Title"],
            "paths": ["/x/a.mp4", "/y/b.mp4"],
            "embedding_spec": None,
        }

        hits = remote_search_service.run_remote_search("cat", is_text=True)
        self.assertEqual(len(hits), 2)
        self.assertIsInstance(hits[0], RemoteSearchHit)
        self.assertEqual(hits[0].title, "A Title")
        self.assertAlmostEqual(hits[0].time_sec, 12.0)
        self.assertAlmostEqual(hits[0].score, 0.95)
        self.assertEqual(hits[0].source_link, "https://a.example")
        self.assertEqual(hits[1].title, "B Title")


class UtilsTests(unittest.TestCase):
    def test_save_vectors_persists_embedding_spec(self):
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as handle:
            vector_file = handle.name
        try:
            vectors = np.array([[1.0, 0.0]], dtype=np.float32)
            timestamps = np.array([0.0], dtype=np.float32)
            embedding_spec = {
                "model_id": "clip_onnx_default",
                "provider": "clip_onnx",
                "embedding_space": "clip_onnx_default",
                "dimension": 512,
                "metric": "ip",
            }

            from src.core.faiss_index import load_vectors, save_vectors

            save_vectors(vectors, timestamps, vector_file, embedding_spec=embedding_spec)
            payload = load_vectors(vector_file)
            self.assertEqual(payload.get("embedding_spec"), embedding_spec)
        finally:
            if os.path.exists(vector_file):
                os.remove(vector_file)

    def test_resolve_sampling_fps_returns_fixed_fps_by_default(self):
        result = utils.resolve_sampling_fps(
            duration_sec=600,
            config={"fps": 2},
        )

        self.assertEqual(result, 2.0)

    def test_resolve_sampling_fps_uses_fixed_mode_even_with_rules(self):
        result = utils.resolve_sampling_fps(
            duration_sec=120,
            config={"fps": 1.5, "sampling_fps_mode": "fixed", "sampling_fps_rules": "0-5m=10"},
        )

        self.assertEqual(result, 1.5)

    def test_resolve_sampling_fps_matches_custom_ranges(self):
        config = {
            "fps": 1,
            "sampling_fps_mode": "dynamic",
            "sampling_fps_rules": "0-10m=2; 10m-30m=1; 30m-=0.25",
        }

        self.assertEqual(utils.resolve_sampling_fps(duration_sec=120, config=config), 2.0)
        self.assertEqual(utils.resolve_sampling_fps(duration_sec=900, config=config), 1.0)
        self.assertEqual(utils.resolve_sampling_fps(duration_sec=3600, config=config), 0.25)

    def test_resolve_sampling_fps_falls_back_to_base_fps_when_no_range_matches(self):
        result = utils.resolve_sampling_fps(
            duration_sec=60,
            config={"fps": 1.5, "sampling_fps_mode": "dynamic", "sampling_fps_rules": "10m-20m=0.8"},
        )

        self.assertEqual(result, 1.5)

    def test_resolve_sampling_fps_uses_narrower_matching_rule_when_ranges_overlap(self):
        result = utils.resolve_sampling_fps(
            duration_sec=120,
            config={"fps": 1, "sampling_fps_mode": "dynamic", "sampling_fps_rules": "0-1h=0.5; 0-10m=2; 10m-30m=1"},
        )

        self.assertEqual(result, 2.0)

    def test_parse_sampling_fps_rules_normalizes_common_separators(self):
        rules = utils.parse_sampling_fps_rules("0-10m=2\uFF1B10m-30m=1\uFF0C30m-=0.4")

        self.assertEqual([rule["fps"] for rule in rules], [2.0, 1.0, 0.4])

    def test_validate_sampling_fps_rules_rejects_invalid_items(self):
        is_valid, _ = utils.validate_sampling_fps_rules("0-10m=2; bad-rule")

        self.assertFalse(is_valid)

    def test_validate_sampling_fps_rules_rejects_missing_units(self):
        is_valid, _ = utils.validate_sampling_fps_rules("0-10m=2; 10-60=1")

        self.assertFalse(is_valid)

    def test_validate_sampling_fps_rules_rejects_non_minute_units(self):
        is_valid, _ = utils.validate_sampling_fps_rules("0-10m=2; 10m-1h=1")

        self.assertFalse(is_valid)

    def test_validate_sampling_fps_rules_rejects_reversed_or_overlapping_ranges(self):
        reversed_valid, _ = utils.validate_sampling_fps_rules("0-10m=2; 60m-1m=1")
        overlap_valid, _ = utils.validate_sampling_fps_rules("0-10m=2; 5m-20m=1")

        self.assertFalse(reversed_valid)
        self.assertFalse(overlap_valid)

    def test_validate_sampling_fps_rules_full_coverage_requires_tail_and_no_gaps(self):
        missing_tail_valid, _ = utils.validate_sampling_fps_rules_full_coverage("0-10m=2; 10m-60m=1")
        gapped_valid, _ = utils.validate_sampling_fps_rules_full_coverage("0-10m=2; 20m-=1")
        complete_valid, _ = utils.validate_sampling_fps_rules_full_coverage("0-10m=2; 10m-60m=1; 60m-=0.5")
        simplified_valid, _ = utils.validate_sampling_fps_rules_full_coverage("0-10m=2; 10m-=1")

        self.assertFalse(missing_tail_valid)
        self.assertFalse(gapped_valid)
        self.assertTrue(complete_valid)
        self.assertTrue(simplified_valid)

    def test_ensure_sampling_fps_rules_open_tail_auto_appends_default_tail(self):
        updated = utils.ensure_sampling_fps_rules_open_tail("0-10m=2; 10m-60m=1", default_tail_fps=1)
        unchanged = utils.ensure_sampling_fps_rules_open_tail("0-10m=2; 10m-=1", default_tail_fps=1)

        self.assertEqual(updated, "0-10m=2; 10m-60m=1; 60m-=1")
        self.assertEqual(unchanged, "0-10m=2; 10m-=1")

    def test_resolve_resource_path_prefers_configured_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured_dir = Path(temp_dir) / "models"
            configured_dir.mkdir()
            target = configured_dir / "clip_text.onnx"
            target.write_bytes(b"model")

            result = utils.resolve_resource_path("models/clip_text.onnx", str(configured_dir))

        self.assertEqual(Path(result), target)

    def test_resolve_resource_path_falls_back_to_packaged_resource(self):
        packaged_path = str(Path("D:/packaged/models/clip_text.onnx"))
        with patch("src.utils.get_resource_path", return_value=packaged_path), patch(
            "src.utils.os.path.exists",
            side_effect=lambda path: path == packaged_path,
        ):
            result = utils.resolve_resource_path("models/clip_text.onnx", "D:/missing-models")

        self.assertEqual(result, packaged_path)

    def test_is_standalone_app_detects_packaged_exe_without_sys_frozen(self):
        with patch.object(utils.sys, "executable", r"D:\Release\main.dist\VideoSeek.exe"), patch.object(
            utils.sys, "frozen", False, create=True
        ):
            self.assertTrue(utils._is_standalone_app())

    def test_get_resource_path_uses_app_install_dir(self):
        with patch.object(utils, "get_app_install_dir", return_value=r"D:\Release\main.dist"):
            resolved = utils.get_resource_path("docs/for-agents.md")
        self.assertEqual(
            os.path.normpath(resolved),
            os.path.normpath(r"D:\Release\main.dist\docs\for-agents.md"),
        )

    def test_get_app_install_dir_dev_uses_repo_root(self):
        with patch.object(utils, "_is_standalone_app", return_value=False):
            install_dir = utils.get_app_install_dir()
        self.assertEqual(
            os.path.normpath(install_dir),
            os.path.normpath(os.path.dirname(os.path.dirname(os.path.abspath(utils.__file__)))),
        )

    def test_get_missing_model_files_reports_missing_entries(self):
        with patch("src.utils.get_model_path", side_effect=lambda filename: f"D:/models/{filename}"), patch(
            "src.utils.os.path.exists",
            side_effect=lambda path: path.endswith("clip_text.onnx"),
        ):
            missing, resolved = utils.get_missing_model_files(["clip_visual.onnx", "clip_text.onnx"])

        self.assertEqual(missing, ["clip_visual.onnx"])
        self.assertEqual(resolved["clip_text.onnx"], "D:/models/clip_text.onnx")

    @patch("src.utils.subprocess.run")
    @patch("src.utils.os.path.exists", return_value=True)
    def test_open_in_explorer_uses_windows_select_argument_split(
        self,
        _mock_exists,
        mock_run,
    ):
        with patch("src.utils.sys.platform", "win32"):
            result = utils.open_in_explorer("D:/videos/clip.mp4")

        self.assertTrue(result)
        mock_run.assert_called_once()
        args = mock_run.call_args.args[0]
        self.assertEqual(args[0], "explorer")
        self.assertEqual(args[1], "/select,")
        self.assertTrue(str(args[2]).lower().endswith("clip.mp4"))

    @patch("src.utils.subprocess.run")
    @patch("src.utils.get_ffmpeg_path", return_value="ffmpeg")
    @patch(
        "src.app.config.load_config",
        return_value={
            "preview_seconds": 6,
            "preview_width": 640,
            "preview_height": 360,
        },
    )
    @patch("src.utils.os.path.exists", return_value=False)
    def test_create_preview_clip_uses_precise_seek_after_input(
        self,
        _mock_exists,
        _mock_load_config,
        _mock_get_ffmpeg,
        mock_run,
    ):
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        utils.create_preview_clip("D:/videos/clip.mp4", 12.3456, "D:/cache/p.mp4")

        cmd = mock_run.call_args.args[0]
        first_ss = cmd.index("-ss")
        i_pos = cmd.index("-i")
        second_ss = cmd.index("-ss", i_pos + 1)
        self.assertLess(first_ss, i_pos)
        self.assertGreater(second_ss, i_pos)
        self.assertEqual(cmd[second_ss + 1], "1.000")
        self.assertIn("-c:a", cmd)
        self.assertIn("aac", cmd)

    @patch("src.utils.subprocess.run")
    @patch("src.utils.get_ffmpeg_path", return_value="ffmpeg")
    @patch(
        "src.app.config.load_config",
        return_value={
            "preview_seconds": 6,
            "preview_width": 640,
            "preview_height": 360,
        },
    )
    @patch("src.utils.os.path.exists", return_value=False)
    def test_create_preview_clip_respects_duration_override(
        self,
        _mock_exists,
        _mock_load_config,
        _mock_get_ffmpeg,
        mock_run,
    ):
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        utils.create_preview_clip("D:/videos/clip.mp4", 10.0, "D:/cache/p.mp4", duration_sec=2.25)

        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("-t") + 1], "2.250")

    @patch("src.utils.subprocess.run")
    @patch("src.utils.get_ffmpeg_path", return_value="ffmpeg")
    @patch("src.utils.ensure_folder_exists")
    @patch("src.utils.os.path.exists", return_value=False)
    def test_export_original_clip_reencode_mode(
        self,
        _mock_exists,
        _mock_ensure_folder_exists,
        _mock_get_ffmpeg,
        mock_run,
    ):
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        utils.export_original_clip("D:/videos/clip.mp4", 8.0, 3.5, "D:/out/clip.mp4")

        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "libx264")
        self.assertEqual(cmd[cmd.index("-crf") + 1], "18")
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "aac")
        self.assertEqual(cmd[cmd.index("-t") + 1], "3.500")

    @patch("src.utils.subprocess.run")
    @patch("src.utils.get_ffmpeg_path", return_value="ffmpeg")
    @patch("src.utils.ensure_folder_exists")
    @patch("src.utils.os.path.exists", return_value=False)
    def test_export_original_clip_copy_mode(
        self,
        _mock_exists,
        _mock_ensure_folder_exists,
        _mock_get_ffmpeg,
        mock_run,
    ):
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        utils.export_original_clip(
            "D:/videos/clip.mp4",
            8.0,
            3.5,
            "D:/out/clip.mp4",
            encode_mode="copy",
        )

        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("-c") + 1], "copy")
        self.assertNotIn("-c:v", cmd)

    @patch("src.utils.subprocess.run")
    @patch("src.utils.get_ffmpeg_path", return_value="ffmpeg")
    @patch("src.utils.ensure_folder_exists")
    @patch("src.utils.os.path.exists", return_value=False)
    def test_export_original_clip_silent_has_no_audio(
        self,
        _mock_exists,
        _mock_ensure_folder_exists,
        _mock_get_ffmpeg,
        mock_run,
    ):
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        utils.export_original_clip("D:/videos/clip.mp4", 8.0, 3.5, "D:/out/clip.mp4", silent=True)

        cmd = mock_run.call_args.args[0]
        self.assertIn("-an", cmd)
        self.assertNotIn("-c:a", cmd)
        self.assertEqual(cmd.count("-map"), 1)


class ModelServiceTests(unittest.TestCase):
    def test_normalize_manifest_uses_base_url_for_missing_file_urls(self):
        manifest = model_service._normalize_manifest(
            {
                "version": "v1",
                "base_url": "https://example.com/models/",
                "files": [{"name": "clip_visual.onnx"}],
            },
            "https://example.com/manifest.json",
        )

        self.assertEqual(manifest["version"], "v1")
        self.assertEqual(
            manifest["files"][0]["sources"][0]["url"],
            "https://example.com/models/clip_visual.onnx",
        )

    def test_normalize_manifest_includes_mirrors(self):
        manifest = model_service._normalize_manifest(
            {
                "base_url": "https://primary.example.com/models/",
                "mirrors": [
                    {"label": "cdn", "base_url": "https://cdn.example.com/models/"},
                    "https://mirror.example.com/models/",
                ],
                "files": [{"name": "clip_visual.onnx"}],
            },
            "https://example.com/manifest.json",
        )

        sources = manifest["files"][0]["sources"]
        self.assertEqual(len(sources), 3)
        self.assertEqual(sources[1]["label"], "cdn")
        self.assertEqual(sources[2]["url"], "https://mirror.example.com/models/clip_visual.onnx")

    def test_normalize_manifest_respects_file_sources(self):
        manifest = model_service._normalize_manifest(
            {
                "base_url": "https://primary.example.com/models/",
                "files": [
                    {
                        "name": "clip_visual.onnx",
                        "sources": [
                            {"label": "oss", "base_url": "https://oss.example.com/models/"},
                            {"label": "github", "url": "https://github.com/example/clip_visual.onnx"},
                        ],
                    }
                ],
            },
            "https://example.com/manifest.json",
        )

        sources = manifest["files"][0]["sources"]
        self.assertEqual(sources[0]["url"], "https://oss.example.com/models/clip_visual.onnx")
        self.assertEqual(sources[1]["label"], "github")


class LibraryDetailServiceTests(unittest.TestCase):
    @patch("src.services.library_service.load_clip_index", return_value=object())
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
        _mock_load_index,
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
        self.assertTrue(result["entries"][0]["vector_exists"])
        self.assertEqual(result["entries"][0]["asset_state"], "ready")
        self.assertFalse(result["entries"][1]["vector_exists"])
        self.assertEqual(result["entries"][1]["asset_state"], "sync_failed")
        self.assertEqual(result["entries"][1]["sync_failure_reason"], "")

    @patch("src.services.library_service.load_clip_index", return_value=object())
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
        _mock_load_index,
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

    @patch("src.services.library_service.load_clip_index", return_value=object())
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
        _mock_load_index,
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

    @patch("src.services.library_service._read_index_health")
    @patch("src.services.library_service._read_vector_health")
    @patch("src.services.library_service.get_local_model_asset_dirs", side_effect=_model_dirs_from_test_config)
    @patch("src.services.library_service.os.path.exists")
    @patch("src.services.library_service.list_libraries")
    @patch("src.services.library_service.load_config")
    def test_list_local_vector_details_skips_deep_validation_by_default(
        self,
        mock_load_config,
        mock_list_libraries,
        mock_exists,
        _mock_model_dirs,
        mock_read_vector_health,
        mock_read_index_health,
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

        mock_read_vector_health.assert_not_called()
        mock_read_index_health.assert_not_called()
        self.assertEqual(result["entries"][0]["asset_state"], "sync_failed")

    @patch("src.services.library_service.load_clip_index", return_value=object())
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
        _mock_load_index,
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
            result["entries"][0]["vector_file"],
            os.path.normpath("D:/migrated-root/data/vector/vid_a_vectors.npy"),
        )
        self.assertEqual(
            result["entries"][0]["index_file"],
            os.path.normpath("D:/migrated-root/data/index/vid_a_index.faiss"),
        )
        self.assertEqual(result["entries"][0]["asset_state"], "ready")


class RemoteLibraryDetailServiceTests(unittest.TestCase):
    @patch("src.services.remote_library_service.get_remote_library_status")
    def test_export_remote_library_zip_writes_expected_files(
        self,
        mock_status,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_file = root / "remote_index.faiss"
            vector_file = root / "remote_vectors.npy"
            zip_path = root / "exports" / "remote_library.zip"
            index_file.write_bytes(b"index-bytes")
            vector_file.write_bytes(b"vector-bytes")
            mock_status.return_value = {
                "ready": True,
                "index_file": str(index_file),
                "vector_file": str(vector_file),
            }

            returned_path = remote_library_service.export_remote_library_zip(str(zip_path))

            self.assertEqual(returned_path, str(zip_path))
            self.assertTrue(zip_path.exists())
            with zipfile.ZipFile(zip_path, "r") as archive:
                self.assertEqual(set(archive.namelist()), {"remote_index.faiss", "remote_vectors.npy"})
                self.assertEqual(archive.read("remote_index.faiss"), b"index-bytes")
                self.assertEqual(archive.read("remote_vectors.npy"), b"vector-bytes")

    @patch("src.services.remote_library_service.get_remote_library_status")
    @patch("src.services.remote_library_service.get_remote_library_paths")
    def test_import_remote_library_zip_restores_expected_files(
        self,
        mock_paths,
        mock_status,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zip_path = root / "remote_library.zip"
            target_index = root / "data" / "remote" / "remote_index.faiss"
            target_vector = root / "data" / "remote" / "remote_vectors.npy"
            mock_paths.return_value = {
                "index_file": str(target_index),
                "vector_file": str(target_vector),
            }
            mock_status.return_value = {
                "ready": True,
                "index_file": str(target_index),
                "vector_file": str(target_vector),
            }

            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("remote_index.faiss", b"imported-index")
                archive.writestr("remote_vectors.npy", b"imported-vectors")

            result = remote_library_service.import_remote_library_zip(str(zip_path))

            self.assertEqual(result["index_file"], str(target_index))
            self.assertEqual(result["vector_file"], str(target_vector))
            self.assertEqual(target_index.read_bytes(), b"imported-index")
            self.assertEqual(target_vector.read_bytes(), b"imported-vectors")

    @patch("src.services.remote_library_service.get_remote_library_paths")
    def test_import_remote_library_zip_rejects_missing_required_entries(
        self,
        mock_paths,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zip_path = root / "broken_remote_library.zip"
            mock_paths.return_value = {
                "index_file": str(root / "data" / "remote" / "remote_index.faiss"),
                "vector_file": str(root / "data" / "remote" / "remote_vectors.npy"),
            }

            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("remote_index.faiss", b"index-only")

            with self.assertRaises(RuntimeError) as ctx:
                remote_library_service.import_remote_library_zip(str(zip_path))

            self.assertIn("missing remote_index.faiss or remote_vectors.npy", str(ctx.exception))

    @patch("src.services.remote_library_service._load_yt_dlp")
    @patch("src.services.remote_library_service.get_data_storage_paths")
    def test_prepare_source_download_uses_migrated_remote_build_cache_dir(
        self,
        mock_storage_paths,
        mock_load_yt_dlp,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "migrated" / "data" / "remote_build_cache"
            resolved_file = cache_dir / "video_1.mp4"
            cache_dir.mkdir(parents=True)
            resolved_file.write_bytes(b"video")
            mock_storage_paths.return_value = {
                "remote_build_cache_dir": str(cache_dir),
            }

            downloader = unittest.mock.MagicMock()
            downloader.__enter__.return_value = downloader
            downloader.__exit__.return_value = False
            downloader.extract_info.return_value = {
                "id": "video_1",
                "title": "Sample",
                "webpage_url": "https://example.com/watch?v=1",
            }
            downloader.prepare_filename.return_value = str(resolved_file)
            mock_load_yt_dlp.return_value = unittest.mock.MagicMock(
                YoutubeDL=unittest.mock.MagicMock(return_value=downloader)
            )

            with patch(
                "src.services.remote_library_service._resolve_downloaded_file",
                return_value=str(resolved_file),
            ):
                result = remote_library_service._prepare_source("https://example.com/watch?v=1", mode="download")

            options = mock_load_yt_dlp.return_value.YoutubeDL.call_args.args[0]
            self.assertEqual(
                options["outtmpl"],
                str(cache_dir / "%(id)s_%(title).80s.%(ext)s"),
            )
            self.assertEqual(result["input"], str(resolved_file))

    @patch("src.services.remote_library_service.get_remote_library_paths")
    @patch("src.services.remote_library_service.get_data_storage_paths")
    def test_write_build_report_uses_migrated_remote_report_path(
        self,
        mock_storage_paths,
        mock_paths,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / "migrated" / "data" / "remote" / "build_report.json"
            mock_storage_paths.return_value = {
                "remote_build_report_file": str(report_path),
            }
            mock_paths.return_value = {
                "index_file": str(root / "migrated" / "data" / "remote" / "remote_index.faiss"),
                "vector_file": str(root / "migrated" / "data" / "remote" / "remote_vectors.npy"),
            }

            returned_path = remote_library_service._write_build_report(
                mode="download",
                requested_links=["https://example.com/watch?v=1"],
                status={
                    "duration_sec": 1.5,
                    "new_vectors": 3,
                    "total_vectors": 3,
                    "success_count": 1,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "success_links": [],
                    "failed_links": [],
                    "skipped_links": [],
                },
                max_frames_per_video=2000,
                sampled_fps=1.0,
            )

            self.assertEqual(returned_path, str(report_path))
            self.assertTrue(report_path.exists())

    @patch("src.services.remote_library_service._write_build_report", return_value="data/remote/build_report.json")
    @patch("src.services.remote_library_service.get_remote_library_status")
    @patch("src.services.remote_library_service.save_remote_vector_payload")
    @patch(
        "src.services.remote_library_service.get_active_embedding_spec",
        return_value={
            "model_id": "clip_onnx_default",
            "provider": "clip_onnx",
            "embedding_space": "clip_onnx_default",
            "dimension": 512,
            "metric": "ip",
        },
    )
    @patch("src.services.remote_library_service.create_clip_index")
    @patch("src.services.remote_library_service.get_clip_embeddings_batch")
    @patch("src.services.remote_library_service._extract_frames")
    @patch("src.services.remote_library_service._probe_duration", return_value=600.0)
    @patch("src.services.remote_library_service._prepare_source")
    @patch("src.services.remote_library_service.get_remote_library_paths")
    @patch("src.services.remote_library_service.load_config")
    def test_build_remote_library_from_links_uses_dynamic_sampling_fps(
        self,
        mock_load_config,
        mock_paths,
        mock_prepare_source,
        _mock_probe_duration,
        mock_extract_frames,
        mock_embeddings,
        mock_create_index,
        _mock_get_embedding_spec,
        mock_save_remote_payload,
        mock_status,
        _mock_write_report,
    ):
        mock_load_config.return_value = {
            "fps": 1,
            "sampling_fps_mode": "dynamic",
            "sampling_fps_rules": "0-5m=2; 5m-20m=0.5; 20m-=0.25",
            "remote_max_frames": 2000,
        }
        mock_paths.return_value = {
            "index_file": "data/remote/remote_index.faiss",
            "vector_file": "data/remote/remote_vectors.npy",
        }
        mock_prepare_source.return_value = {
            "input": "https://example.com/video.mp4",
            "http_headers": None,
            "source_link": "https://example.com/watch?v=1",
            "source_id": "source_1",
            "title": "Sample",
        }
        mock_extract_frames.return_value = ([np.zeros((224, 224, 3), dtype=np.uint8)], [0.0])
        mock_embeddings.return_value = np.array([[1.0, 0.0]], dtype=np.float32)
        mock_create_index.return_value = object()
        mock_status.return_value = {
            "ready": True,
            "index_file": "data/remote/remote_index.faiss",
            "vector_file": "data/remote/remote_vectors.npy",
        }

        remote_library_service.build_remote_library_from_links(
            ["https://example.com/watch?v=1"],
            incremental=False,
        )

        self.assertAlmostEqual(mock_extract_frames.call_args.kwargs["fps"], 0.5)
        payload = mock_save_remote_payload.call_args.args[1]
        self.assertEqual(payload["embedding_spec"]["model_id"], "clip_onnx_default")

    @patch("src.services.remote_library_service._load_existing_payload")
    @patch("src.services.remote_library_service.os.path.exists", return_value=True)
    @patch("src.services.remote_library_service.get_remote_library_status")
    def test_list_remote_link_details_groups_by_source(
        self,
        mock_status,
        _mock_exists,
        mock_payload,
    ):
        mock_status.return_value = {
            "ready": True,
            "index_file": "data/remote/remote_index.faiss",
            "vector_file": "data/remote/remote_vectors.npy",
        }
        mock_payload.return_value = {
            "source_links": ["https://a", "https://a", "https://b"],
            "titles": ["A", "A", "B"],
            "paths": ["id_a", "id_a", "id_b"],
            "timestamps": [1.0, 2.5, 0.5],
        }

        result = remote_library_service.list_remote_link_details()

        self.assertEqual(result["total_vectors"], 3)
        self.assertEqual(result["total_links"], 2)
        first = result["entries"][0]
        self.assertEqual(first["source_link"], "https://a")
        self.assertEqual(first["frames"], 2)
        self.assertAlmostEqual(first["min_time"], 1.0)
        self.assertAlmostEqual(first["max_time"], 2.5)


class MigratedStorageWorkflowTests(unittest.TestCase):
    def test_delete_physical_video_data_uses_current_config_storage_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            migrated_root = Path(temp_dir) / "migrated-root" / "data"
            vector_dir = migrated_root / "vector"
            index_dir = migrated_root / "index"
            vector_dir.mkdir(parents=True)
            index_dir.mkdir(parents=True)

            vector_file = vector_dir / "vid_a_vectors.npy"
            index_file = index_dir / "vid_a_index.faiss"
            vector_file.write_bytes(b"vector")
            index_file.write_bytes(b"index")

            config = {
                "vector_dir": str(vector_dir),
                "index_dir": str(index_dir),
            }

            with patch(
                "src.workflows.update_video.get_local_model_asset_dirs",
                return_value={"vector_dir": str(vector_dir), "index_dir": str(index_dir)},
            ):
                update_video.delete_physical_video_data("vid_a", config)

            self.assertFalse(vector_file.exists())
            self.assertFalse(index_file.exists())


class ModelPackageServiceTests(unittest.TestCase):
    def test_import_updates_legacy_default_profile_with_empty_variant(self):
        with tempfile.TemporaryDirectory() as model_root:
            manifest_dir = Path(model_root) / "openai-clip" / "vit-base-patch32"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "clip_visual.onnx").write_bytes(b"dummy")
            (manifest_dir / "model_manifest.json").write_text(
                json.dumps(
                    {
                        "id": "clip_onnx_default",
                        "provider": "clip_onnx",
                        "variant": "vit-base-patch32",
                        "display_name": "CLIP ONNX",
                        "required_files": ["clip_visual.onnx"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            config = {
                "models": {
                    "active_profile": "clip_onnx_default",
                    "profiles": [
                        {
                            "id": "clip_onnx_default",
                            "provider": "clip_onnx",
                            "display_name": "CLIP ONNX",
                            "enabled": True,
                            "runtime": {
                                "prefer_gpu": True,
                                "model_dir": model_root,
                                "model_variant": "",
                            },
                            "files": {"visual_model": "clip_visual.onnx"},
                        }
                    ],
                }
            }

            with (
                patch("src.services.model_package_service.load_config", return_value=config),
                patch("src.services.model_package_service.save_config") as mock_save_config,
                patch("src.services.model_package_service.get_config_schema_version", return_value=2),
            ):
                result = model_package_service.import_model_packages(model_root)

            self.assertEqual(result["imported"], 0)
            self.assertEqual(result["updated"], 1)
            self.assertEqual(result["errors"], [])
            self.assertTrue(mock_save_config.called)
            self.assertEqual(config["models"]["profiles"][0]["runtime"]["model_variant"], "vit-base-patch32")


class ModelResourceDirTests(unittest.TestCase):
    def test_resolve_model_resource_dir_prefers_legacy_chinese_clip_onnx_folder(self):
        from src.storage.config_store import resolve_model_resource_dir

        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_dir = os.path.join(temp_dir, "chinese-clip-onnx", "vit-base-patch16")
            os.makedirs(legacy_dir, exist_ok=True)
            marker = os.path.join(legacy_dir, "chinese_clip_text.onnx")
            with open(marker, "wb") as handle:
                handle.write(b"onnx")

            resolved = resolve_model_resource_dir(temp_dir, "chinese_clip_onnx", "vit-base-patch16")

            self.assertEqual(os.path.normcase(resolved), os.path.normcase(legacy_dir))


if __name__ == "__main__":
    unittest.main()
