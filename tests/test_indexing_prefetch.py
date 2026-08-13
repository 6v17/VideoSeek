import threading
import time
import unittest
from unittest import mock

from src.services import indexing_service


class IndexingVideoWorkersResolveTests(unittest.TestCase):
    def test_resolve_clamps_and_defaults(self):
        self.assertEqual(indexing_service.resolve_indexing_video_workers({"indexing_video_workers": 1}), 1)
        self.assertEqual(indexing_service.resolve_indexing_video_workers({"indexing_video_workers": 2}), 2)
        self.assertEqual(indexing_service.resolve_indexing_video_workers({"indexing_video_workers": 99}), 2)
        self.assertEqual(indexing_service.resolve_indexing_video_workers({"indexing_video_workers": 0}), 1)

    def test_resolve_env_override(self):
        with mock.patch.dict("os.environ", {"VIDEOSEEK_INDEX_VIDEO_WORKERS": "1"}, clear=False):
            self.assertEqual(
                indexing_service.resolve_indexing_video_workers({"indexing_video_workers": 2}),
                1,
            )


class IndexingPrefetchOrderedCommitTests(unittest.TestCase):
    def test_workers_two_commits_in_plan_order(self):
        root = "D:\\videos"
        lib_files = {}
        paths = [f"{root}\\a.mp4", f"{root}\\b.mp4", f"{root}\\c.mp4"]
        release_b = threading.Event()
        commit_order = []

        def fake_compute(abs_path, *args, **kwargs):
            if abs_path.endswith("a.mp4"):
                release_b.wait(timeout=2.0)
                time.sleep(0.05)
            elif abs_path.endswith("b.mp4"):
                release_b.set()
            return {
                "kind": "generated",
                "abs_path": abs_path,
                "rel_path": abs_path.split("\\")[-1],
                "library_path": root,
                "video_mod_time": 1.0,
                "video_id": abs_path,
                "vectors": [1],
                "timestamps": [0.0],
                "chunks": [],
                "chunk_config": {},
                "had_saved_vid": False,
            }

        def fake_commit(_lib_files, result, **_kwargs):
            commit_order.append(result["abs_path"])
            return ([1], [0.0], True, True)

        with mock.patch.object(indexing_service, "_index_video_compute", side_effect=fake_compute), mock.patch.object(
            indexing_service, "_index_video_commit", side_effect=fake_commit
        ):
            failed, changed, last_index = indexing_service._run_planned_videos_with_prefetch(
                paths,
                root_path=root,
                lib_files=lib_files,
                config={"indexing_video_workers": 2},
                get_video_id=lambda path: path,
                issue_callback=None,
                should_stop_callback=None,
                progress_callback=None,
                indexed_ids=set(),
                meta={"libraries": {}},
                workers=2,
                global_file_index_start=0,
                total_files=3,
                report_scan_progress=lambda *_a, **_k: None,
                queue_meta_persist=lambda: None,
            )

        self.assertEqual(failed, [])
        self.assertTrue(changed)
        self.assertEqual(commit_order, paths)
        self.assertEqual(last_index, 3)

    def test_workers_one_uses_process_single_video(self):
        root = "D:\\videos"
        paths = [f"{root}\\a.mp4", f"{root}\\b.mp4"]
        calls = []

        def fake_process(abs_path, *args, **kwargs):
            calls.append(abs_path)
            return ([1], [0.0], True, False)

        with mock.patch.object(indexing_service, "process_single_video", side_effect=fake_process):
            failed, changed, last_index = indexing_service._run_planned_videos_with_prefetch(
                paths,
                root_path=root,
                lib_files={},
                config={"indexing_video_workers": 1},
                get_video_id=lambda path: "vid",
                issue_callback=None,
                should_stop_callback=None,
                progress_callback=None,
                indexed_ids=set(),
                meta={"libraries": {}},
                workers=1,
                global_file_index_start=0,
                total_files=2,
                report_scan_progress=lambda *_a, **_k: None,
                queue_meta_persist=lambda: None,
            )

        self.assertEqual(failed, [])
        self.assertFalse(changed)
        self.assertEqual(calls, paths)
        self.assertEqual(last_index, 2)

    def test_stop_cancels_pending_without_extra_commits(self):
        root = "D:\\videos"
        paths = [f"{root}\\a.mp4", f"{root}\\b.mp4", f"{root}\\c.mp4"]
        stop_after_a = threading.Event()
        commit_order = []

        def fake_compute(abs_path, *args, **kwargs):
            if abs_path.endswith("a.mp4"):
                time.sleep(0.08)
                stop_after_a.set()
            else:
                stop_after_a.wait(timeout=2.0)
                time.sleep(0.2)
            return {
                "kind": "generated",
                "abs_path": abs_path,
                "rel_path": abs_path.split("\\")[-1],
                "library_path": root,
                "video_mod_time": 1.0,
                "video_id": abs_path,
                "vectors": [1],
                "timestamps": [0.0],
                "had_saved_vid": False,
            }

        def fake_commit(_lib_files, result, **_kwargs):
            commit_order.append(result["abs_path"])
            return ([1], [0.0], True, True)

        def should_stop():
            return stop_after_a.is_set() and len(commit_order) >= 1

        with mock.patch.object(indexing_service, "_index_video_compute", side_effect=fake_compute), mock.patch.object(
            indexing_service, "_index_video_commit", side_effect=fake_commit
        ):
            with self.assertRaises(indexing_service.IndexUpdateInterrupted):
                indexing_service._run_planned_videos_with_prefetch(
                    paths,
                    root_path=root,
                    lib_files={},
                    config={"indexing_video_workers": 2},
                    get_video_id=lambda path: path,
                    issue_callback=None,
                    should_stop_callback=should_stop,
                    progress_callback=None,
                    indexed_ids=set(),
                    meta={"libraries": {}},
                    workers=2,
                    global_file_index_start=0,
                    total_files=3,
                    report_scan_progress=lambda *_a, **_k: None,
                    queue_meta_persist=lambda: None,
                )

        # At least A committed; C should not have been committed after stop.
        self.assertTrue(commit_order)
        self.assertEqual(commit_order[0], paths[0])
        self.assertNotIn(paths[2], commit_order)


if __name__ == "__main__":
    unittest.main()
