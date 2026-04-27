import io
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from src.core.extract_frames import extract_frames_with_ffmpeg, stream_frames_with_ffmpeg
from src.utils import get_video_duration_seconds, get_video_stream_info, has_readable_video_stream


class ExtractFramesTests(unittest.TestCase):
    @patch("src.core.extract_frames.subprocess.Popen")
    @patch("src.core.extract_frames.get_ffmpeg_path", return_value="ffmpeg")
    @patch("src.core.extract_frames.resolve_sampling_fps", return_value=2.0)
    @patch("src.core.extract_frames.get_video_duration_seconds", return_value=10.0)
    @patch("src.core.extract_frames.load_config", return_value={"fps": 1})
    def test_extract_frames_uses_fixed_scaled_rawvideo_output(
        self,
        _mock_load_config,
        _mock_duration,
        _mock_resolve_fps,
        _mock_ffmpeg,
        mock_popen,
    ):
        frame_bytes = np.zeros((224, 224, 3), dtype=np.uint8).tobytes()
        process = MagicMock()
        process.stdout = io.BytesIO(frame_bytes)
        process.stderr = io.BytesIO(b"")
        process.wait.return_value = 0
        process.poll.return_value = 0
        mock_popen.return_value = process

        frames, timestamps = extract_frames_with_ffmpeg("D:/video.mp4")

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].shape, (224, 224, 3))
        self.assertEqual(timestamps, [0.0])
        command = mock_popen.call_args.args[0]
        self.assertIn("fps=2.000000,scale=224:224", command)

    @patch("src.core.extract_frames.subprocess.Popen")
    @patch("src.core.extract_frames.get_ffmpeg_path", return_value="ffmpeg")
    @patch("src.core.extract_frames.resolve_sampling_fps", return_value=2.0)
    @patch("src.core.extract_frames.get_video_duration_seconds", return_value=10.0)
    @patch("src.core.extract_frames.load_config", return_value={"fps": 1})
    def test_stream_frames_yields_frames_without_materializing_full_list(
        self,
        _mock_load_config,
        _mock_duration,
        _mock_resolve_fps,
        _mock_ffmpeg,
        mock_popen,
    ):
        frame_bytes = np.zeros((224, 224, 3), dtype=np.uint8).tobytes()
        process = MagicMock()
        process.stdout = io.BytesIO(frame_bytes + frame_bytes)
        process.stderr = io.BytesIO(b"")
        process.wait.return_value = 0
        process.poll.return_value = 0
        mock_popen.return_value = process

        items = list(stream_frames_with_ffmpeg("D:/video.mp4"))

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0][0].shape, (224, 224, 3))
        self.assertEqual(items[0][1], 0.0)
        self.assertEqual(items[1][1], 0.5)


class VideoProbeTests(unittest.TestCase):
    @patch("src.utils.get_ffprobe_path", return_value="ffprobe")
    @patch("src.utils.subprocess.run")
    def test_get_video_stream_info_reads_ffprobe_json(self, mock_run, _mock_ffprobe):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"streams":[{"width":1920,"height":1080}],"format":{"duration":"12.5"}}',
        )

        info = get_video_stream_info("D:/video.mp4")

        self.assertEqual(info["width"], 1920)
        self.assertEqual(info["height"], 1080)
        self.assertEqual(info["duration"], 12.5)

    @patch("src.utils._probe_video_duration_with_opencv", return_value=8.0)
    @patch("src.utils.get_video_stream_info", return_value={"width": None, "height": None, "duration": None})
    def test_get_video_duration_seconds_falls_back_when_ffprobe_unavailable(self, _mock_info, mock_fallback):
        duration = get_video_duration_seconds("D:/video.mp4")

        self.assertEqual(duration, 8.0)
        mock_fallback.assert_called_once_with("D:/video.mp4")

    @patch("src.utils.get_video_stream_info", return_value={"width": 1920, "height": 1080, "duration": None})
    def test_has_readable_video_stream_prefers_ffprobe_dimensions(self, _mock_info):
        self.assertTrue(has_readable_video_stream("D:/video.mp4"))

    @patch(
        "src.utils._probe_video_stream_with_opencv",
        return_value={"width": 1280, "height": 720, "duration": 5.0},
    )
    @patch("src.utils.get_video_stream_info", return_value={"width": None, "height": None, "duration": None})
    def test_has_readable_video_stream_falls_back_to_opencv_dimensions(self, _mock_info, _mock_probe):
        self.assertTrue(has_readable_video_stream("D:/video.mp4"))


if __name__ == "__main__":
    unittest.main()
