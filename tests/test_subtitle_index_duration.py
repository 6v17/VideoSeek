import os
import tempfile
import unittest
from unittest.mock import patch


class SubtitleIndexDurationTests(unittest.TestCase):
    def test_probe_failure_does_not_mark_ready_with_empty_transcript(self):
        from src.services.subtitle_index_service import index_video_subtitles

        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "clip.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"not-a-real-video")

            with patch(
                "src.services.subtitle_index_service.get_video_duration_seconds",
                return_value=None,
            ), patch(
                "src.services.subtitle_index_service.ensure_subtitle_ocr_ready",
                return_value=(True, ""),
            ), patch(
                "src.services.subtitle_index_service.save_dialogue_transcript"
            ) as save_mock, patch(
                "src.services.subtitle_index_service.set_dialogue_index_state"
            ) as state_mock:
                result = index_video_subtitles(
                    "vid-1",
                    video_path,
                    mode="ocr",
                    persist=True,
                    config={},
                )

        self.assertFalse(result.get("ok"))
        self.assertIn("duration", str(result.get("error") or "").lower())
        save_mock.assert_not_called()
        self.assertTrue(state_mock.called)
        args, kwargs = state_mock.call_args
        self.assertEqual(args[2], "failed")

    def test_empty_ocr_does_not_wipe_previous_transcript(self):
        from src.services.subtitle_index_service import index_video_subtitles

        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "clip.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"not-a-real-video")

            prior = [{"start": 0.0, "end": 1.0, "text": "hello"}]
            with patch(
                "src.services.subtitle_index_service.get_video_duration_seconds",
                return_value=12.0,
            ), patch(
                "src.services.subtitle_index_service.ensure_subtitle_ocr_ready",
                return_value=(True, ""),
            ), patch(
                "src.services.subtitle_index_service._build_probe_times_timeline",
                return_value=([1.0, 2.0], 2),
            ), patch(
                "src.services.subtitle_index_service.collect_ocr_observations",
                return_value=[],
            ), patch(
                "src.services.subtitle_index_service.merge_ocr_observations",
                return_value=[],
            ), patch(
                "src.services.subtitle_index_service.list_shared_transcript_segments",
                return_value=prior,
            ), patch(
                "src.services.subtitle_index_service.save_dialogue_transcript"
            ) as save_mock, patch(
                "src.services.subtitle_index_service.set_dialogue_index_state"
            ) as state_mock, patch(
                "src.services.subtitle_index_service.resolve_subtitle_sample_strategy",
                return_value="timeline",
            ):
                result = index_video_subtitles(
                    "vid-1",
                    video_path,
                    mode="ocr",
                    persist=True,
                    config={},
                    sample_strategy="timeline",
                )

        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("kept_previous"))
        save_mock.assert_not_called()
        self.assertEqual(state_mock.call_args.args[2], "failed")


if __name__ == "__main__":
    unittest.main()
