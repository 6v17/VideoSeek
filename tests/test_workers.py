import unittest
import os
from unittest.mock import patch

from ui.workers import IndexUpdateWorker


class WorkersTests(unittest.TestCase):
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

        def capture_env(**_kwargs):
            seen["gpu"] = os.environ.get("VIDEOSEEK_DEBUG_FORCE_GPU_OOM")
            seen["system"] = os.environ.get("VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM")
            return (None, None, None, None)

        mock_update_flow.side_effect = capture_env
        worker = IndexUpdateWorker(target_lib="D:/videos", debug_failure="gpu_oom")

        worker.run()

        self.assertEqual(seen, {"gpu": "1", "system": None})
        self.assertIsNone(os.environ.get("VIDEOSEEK_DEBUG_FORCE_GPU_OOM"))
        self.assertIsNone(os.environ.get("VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM"))


if __name__ == "__main__":
    unittest.main()
