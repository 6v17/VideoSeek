import unittest
import os
from unittest.mock import MagicMock, patch

from ui.workers import (
    IndexUpdateWorker,
    SearchConfig,
    SearchWorker,
    TeamConnectWorker,
    TeamServerLifecycleWorker,
    VersionCheckWorker,
)


class WorkersTests(unittest.TestCase):
    def test_index_update_stop_kills_the_active_extract(self):
        worker = IndexUpdateWorker(target_lib="D:/videos")
        with patch("src.core.clip_embedding.stop_active_index_extracts") as stop_extracts:
            worker.stop()
        self.assertTrue(worker._stop_requested)
        stop_extracts.assert_called_once_with()

    @patch("src.workflows.update_video.update_videos_flow")
    @patch("src.core.clip_embedding.get_engine_runtime_status", return_value={})
    @patch("src.core.clip_embedding.prepare_inference_runtime", return_value={})
    def test_index_update_worker_keeps_collected_issues_when_stopped(
        self,
        _mock_prepare_runtime,
        _mock_runtime_status,
        mock_update_flow,
    ):
        emitted = []
        worker = IndexUpdateWorker(target_lib="D:/videos")
        worker.finished_signal.connect(lambda success, stopped, has_assets, issues: emitted.append((success, stopped, has_assets, issues)))

        def interrupted_update(**kwargs):
            kwargs["issue_callback"](
                {
                    "library_path": "D:/videos",
                    "video_rel_path": "broken.mp4",
                    "abs_path": "D:/videos/broken.mp4",
                    "action": "skipped",
                    "reason": "processing_error",
                }
            )
            raise InterruptedError("stopped")

        mock_update_flow.side_effect = interrupted_update

        worker.run()

        self.assertEqual(len(emitted), 1)
        success, stopped, has_assets, issues = emitted[0]
        self.assertFalse(success)
        self.assertTrue(stopped)
        self.assertFalse(has_assets)
        self.assertEqual(
            issues,
            [
                {
                    "library_path": "D:/videos",
                    "video_rel_path": "broken.mp4",
                    "abs_path": "D:/videos/broken.mp4",
                    "action": "skipped",
                    "reason": "processing_error",
                }
            ],
        )

    @patch("src.workflows.update_video.update_videos_flow", side_effect=RuntimeError("gpu out of memory"))
    @patch("src.core.clip_embedding.get_engine_runtime_status", return_value={})
    @patch("src.core.clip_embedding.prepare_inference_runtime", return_value={})
    def test_index_update_worker_emits_error_signal_on_unexpected_failure(
        self,
        _mock_prepare_runtime,
        _mock_runtime_status,
        _mock_update_flow,
    ):
        finished = []
        errors = []
        worker = IndexUpdateWorker(target_lib="D:/videos")
        worker.finished_signal.connect(lambda success, stopped, has_assets, issues: finished.append((success, stopped, has_assets, issues)))
        worker.error_signal.connect(errors.append)

        worker.run()

        self.assertEqual(errors, ["gpu out of memory"])
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0], (False, False, False, []))

    @patch("src.core.clip_embedding.get_engine_runtime_status", return_value={})
    @patch("src.core.clip_embedding.prepare_inference_runtime", return_value={})
    @patch("src.workflows.update_video.update_videos_flow")
    def test_index_update_worker_applies_debug_failure_only_for_current_run(
        self,
        mock_update_flow,
        _mock_prepare_runtime,
        _mock_runtime_status,
    ):
        seen = {}
        os.environ.pop("VIDEOSEEK_DEBUG_FORCE_GPU_OOM", None)
        os.environ.pop("VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM", None)

        def capture_env(**kwargs):
            seen["debug_failure"] = kwargs.get("debug_failure")
            seen["gpu"] = os.environ.get("VIDEOSEEK_DEBUG_FORCE_GPU_OOM")
            seen["system"] = os.environ.get("VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM")
            return (None, None, None, None)

        mock_update_flow.side_effect = capture_env
        worker = IndexUpdateWorker(target_lib="D:/videos", debug_failure="gpu_oom")

        worker.run()

        self.assertEqual(seen, {"debug_failure": "gpu_oom", "gpu": None, "system": None})
        self.assertIsNone(os.environ.get("VIDEOSEEK_DEBUG_FORCE_GPU_OOM"))
        self.assertIsNone(os.environ.get("VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM"))

    @patch("src.services.version_service.get_version_status", return_value={"ok": True})
    def test_version_check_worker_emits_result(self, _mock_get_version_status):
        emitted = []
        worker = VersionCheckWorker("zh")
        worker.result_ready.connect(emitted.append)

        worker.run()

        self.assertEqual(emitted, [{"ok": True}])

    @patch("src.services.version_service.get_version_status", side_effect=RuntimeError("network down"))
    def test_version_check_worker_swallows_fetch_errors(self, _mock_get_version_status):
        emitted = []
        worker = VersionCheckWorker("zh")
        worker.result_ready.connect(emitted.append)

        worker.run()

        self.assertEqual(emitted, [])

    @patch("src.services.search_service.run_search", side_effect=RuntimeError("search failed"))
    def test_search_worker_emits_error_signal(self, _mock_run_search):
        errors = []
        worker = SearchWorker(SearchConfig(query="cat", is_text=True))
        worker.error_signal.connect(errors.append)

        worker.run()

        self.assertEqual(errors, ["search failed"])

    @patch("src.services.search_service.run_search", side_effect=InterruptedError("search stopped"))
    def test_search_worker_interrupted_does_not_emit_error(self, mock_run_search):
        errors = []
        results = []
        worker = SearchWorker(SearchConfig(query="cat", is_text=True))
        worker.error_signal.connect(errors.append)
        worker.result_ready.connect(results.append)

        worker.run()

        mock_run_search.assert_called_once()
        self.assertEqual(errors, [])
        self.assertEqual(results, [])

    @patch("src.services.search_service.run_search")
    def test_search_worker_passes_should_stop_callback(self, mock_run_search):
        mock_run_search.return_value = []
        worker = SearchWorker(SearchConfig(query="cat", is_text=True))
        worker.run()
        kwargs = mock_run_search.call_args.kwargs
        self.assertTrue(callable(kwargs.get("should_stop_callback")))
        worker.stop()
        self.assertTrue(kwargs["should_stop_callback"]())

    def test_team_connect_stop_skips_session_and_finished(self):
        worker = TeamConnectWorker("client", "http://127.0.0.1:9")
        finished = []
        worker.finished_signal.connect(finished.append)
        worker.stop()

        with patch("src.services.team_client_search.prepare_team_client_session") as prepare:
            worker.run()

        prepare.assert_not_called()
        self.assertEqual(finished, [])

    def test_team_connect_stop_after_prepare_does_not_emit_finished(self):
        worker = TeamConnectWorker("client", "http://127.0.0.1:9")
        finished = []
        worker.finished_signal.connect(finished.append)

        def _prepare(*_args, **_kwargs):
            worker.stop()
            return {"libraries": []}

        with patch("src.services.team_client_search.prepare_team_client_session", side_effect=_prepare):
            worker.run()

        self.assertEqual(finished, [])

    def test_team_lifecycle_stop_skips_start(self):
        controller = MagicMock()
        worker = TeamServerLifecycleWorker(controller, "start")
        finished = []
        worker.finished_signal.connect(finished.append)
        worker.stop()

        worker.run()

        controller.start_server.assert_not_called()
        self.assertEqual(finished, [])


if __name__ == "__main__":
    unittest.main()
