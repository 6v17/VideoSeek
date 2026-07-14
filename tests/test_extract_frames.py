import io
import os
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from src.core.extract_frames import (
    FrameExtractionError,
    _build_cpu_extract_command,
    _build_d3d11va_extract_command,
    extract_frames_with_ffmpeg,
    ffmpeg_supports_d3d11va,
    is_experimental_hw_decode_enabled,
    stream_frames_with_ffmpeg,
)
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
        self.assertIn("fps=2.000000,scale=224:224:flags=fast_bilinear", command)

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

    @patch.dict(os.environ, {"VIDEOSEEK_FFMPEG_THREADS": "4"}, clear=False)
    @patch("src.core.extract_frames.subprocess.Popen")
    @patch("src.core.extract_frames.get_ffmpeg_path", return_value="ffmpeg")
    @patch("src.core.extract_frames.resolve_sampling_fps", return_value=2.0)
    @patch("src.core.extract_frames.get_video_duration_seconds", return_value=10.0)
    @patch("src.core.extract_frames.load_config", return_value={"fps": 1})
    def test_extract_ffmpeg_threads_env_caps_decode_threads(
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
        process.wait.return_value = 0
        process.poll.return_value = 0
        mock_popen.return_value = process

        extract_frames_with_ffmpeg("D:/video.mp4")

        command = mock_popen.call_args.args[0]
        idx = command.index("-threads")
        self.assertEqual(command[idx + 1], "4")

    @patch("src.core.extract_frames.subprocess.Popen")
    @patch("src.core.extract_frames.get_ffmpeg_path", return_value="ffmpeg")
    @patch("src.core.extract_frames.resolve_sampling_fps", return_value=2.0)
    @patch("src.core.extract_frames.get_video_duration_seconds", return_value=10.0)
    @patch("src.core.extract_frames.load_config", return_value={"fps": 1})
    def test_stream_frames_raises_when_ffmpeg_exits_nonzero(
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
        process.wait.return_value = 1
        process.poll.return_value = 1
        mock_popen.return_value = process

        with self.assertRaises(FrameExtractionError) as ctx:
            list(stream_frames_with_ffmpeg("D:/video.mp4"))

        self.assertEqual(ctx.exception.frame_count, 1)

    @patch("src.core.extract_frames.subprocess.Popen")
    @patch("src.core.extract_frames.get_ffmpeg_path", return_value="ffmpeg")
    @patch("src.core.extract_frames.resolve_sampling_fps", return_value=2.0)
    @patch("src.core.extract_frames.get_video_duration_seconds", return_value=10.0)
    @patch("src.core.extract_frames.load_config", return_value={"fps": 1})
    def test_stream_frames_raises_on_stop_request(
        self,
        _mock_load_config,
        _mock_duration,
        _mock_resolve_fps,
        _mock_ffmpeg,
        mock_popen,
    ):
        frame_bytes = np.zeros((224, 224, 3), dtype=np.uint8).tobytes()
        process = MagicMock()
        process.stdout = io.BytesIO(frame_bytes * 50)
        process.wait.return_value = 0
        process.poll.return_value = 0
        mock_popen.return_value = process

        stop_after = {"count": 0}

        def should_stop():
            stop_after["count"] += 1
            return stop_after["count"] > 1

        with self.assertRaises(InterruptedError):
            list(
                stream_frames_with_ffmpeg(
                    "D:/video.mp4",
                    should_stop=should_stop,
                    process_holder={},
                )
            )

    @patch("src.core.extract_frames._stream_rawvideo_frames")
    @patch("src.core.extract_frames.load_config", return_value={"fps": 1, "experimental_hw_decode": False})
    @patch("src.core.extract_frames.resolve_sampling_fps", return_value=2.0)
    @patch("src.core.extract_frames.get_video_duration_seconds", return_value=10.0)
    def test_stream_frames_uses_cpu_when_hw_decode_disabled(
        self,
        _mock_duration,
        _mock_resolve_fps,
        _mock_load_config,
        mock_stream,
    ):
        mock_stream.return_value = iter([])

        list(stream_frames_with_ffmpeg("D:/video.mp4"))

        mock_stream.assert_called_once()
        self.assertEqual(mock_stream.call_args.kwargs["decode_backend"], "cpu")

    @patch("src.core.extract_frames._stream_rawvideo_frames")
    @patch("src.core.extract_frames.get_video_stream_info", return_value={"pix_fmt": "yuv420p", "profile": "main"})
    @patch("src.core.extract_frames.ffmpeg_supports_d3d11va", return_value=True)
    @patch("src.core.extract_frames.is_experimental_hw_decode_enabled", return_value=True)
    @patch("src.core.extract_frames.load_config", return_value={"fps": 1, "experimental_hw_decode": True})
    @patch("src.core.extract_frames.resolve_sampling_fps", return_value=2.0)
    @patch("src.core.extract_frames.get_video_duration_seconds", return_value=10.0)
    def test_stream_frames_tries_d3d11va_when_enabled(
        self,
        _mock_duration,
        _mock_resolve_fps,
        _mock_load_config,
        _mock_enabled,
        _mock_probe,
        _mock_stream_info,
        mock_stream,
    ):
        mock_stream.return_value = iter([])

        list(stream_frames_with_ffmpeg("D:/video.mp4"))

        self.assertEqual(mock_stream.call_args.kwargs["decode_backend"], "d3d11va")

    @patch("src.core.extract_frames._stream_rawvideo_frames")
    @patch("src.core.extract_frames.get_video_stream_info", return_value={"pix_fmt": "yuv420p", "profile": "main"})
    @patch("src.core.extract_frames.system_has_nvidia_gpu", return_value=True)
    @patch("src.core.extract_frames.ffmpeg_supports_d3d11va", return_value=True)
    @patch("src.core.extract_frames.is_experimental_hw_decode_enabled", return_value=True)
    @patch("src.core.extract_frames.load_config", return_value={"fps": 1, "experimental_hw_decode": True})
    @patch("src.core.extract_frames.resolve_sampling_fps", return_value=2.0)
    @patch("src.core.extract_frames.get_video_duration_seconds", return_value=10.0)
    def test_stream_frames_nvidia_tries_p010_after_nv12_failure(
        self,
        _mock_duration,
        _mock_resolve_fps,
        _mock_load_config,
        _mock_enabled,
        _mock_probe,
        _mock_nvidia,
        _mock_stream_info,
        mock_stream,
    ):
        mock_stream.side_effect = [
            FrameExtractionError("nv12 failed", frame_count=0),
            iter([]),
        ]

        list(stream_frames_with_ffmpeg("D:/video.mkv"))

        self.assertEqual(mock_stream.call_count, 2)
        self.assertEqual(mock_stream.call_args_list[0].kwargs["decode_backend"], "d3d11va")
        self.assertEqual(mock_stream.call_args_list[1].kwargs["decode_backend"], "d3d11va_p010")

    @patch("src.core.extract_frames._stream_rawvideo_frames")
    @patch("src.core.extract_frames.get_video_stream_info", return_value={"pix_fmt": "yuv420p", "profile": "main"})
    @patch("src.core.extract_frames.system_has_nvidia_gpu", return_value=False)
    @patch("src.core.extract_frames.ffmpeg_supports_d3d11va", return_value=True)
    @patch("src.core.extract_frames.is_experimental_hw_decode_enabled", return_value=True)
    @patch("src.core.extract_frames.load_config", return_value={"fps": 1, "experimental_hw_decode": True})
    @patch("src.core.extract_frames.resolve_sampling_fps", return_value=2.0)
    @patch("src.core.extract_frames.get_video_duration_seconds", return_value=10.0)
    def test_stream_frames_falls_back_to_cpu_after_d3d11va_failure(
        self,
        _mock_duration,
        _mock_resolve_fps,
        _mock_load_config,
        _mock_enabled,
        _mock_probe,
        _mock_nvidia,
        _mock_stream_info,
        mock_stream,
    ):
        mock_stream.side_effect = [
            FrameExtractionError("d3d11va failed", frame_count=0),
            iter([]),
        ]

        list(stream_frames_with_ffmpeg("D:/video.mp4"))

        self.assertEqual(mock_stream.call_count, 2)
        self.assertEqual(mock_stream.call_args_list[0].kwargs["decode_backend"], "d3d11va")
        self.assertEqual(mock_stream.call_args_list[1].kwargs["decode_backend"], "cpu")

    @patch("src.core.extract_frames._stream_rawvideo_frames")
    @patch(
        "src.core.extract_frames.get_video_stream_info",
        return_value={"pix_fmt": "yuv420p10le", "profile": "main 10", "bits_per_raw_sample": 10},
    )
    @patch("src.core.extract_frames.system_has_nvidia_gpu", return_value=False)
    @patch("src.core.extract_frames.ffmpeg_supports_d3d11va", return_value=True)
    @patch("src.core.extract_frames.is_experimental_hw_decode_enabled", return_value=True)
    @patch("src.core.extract_frames.load_config", return_value={"fps": 1, "experimental_hw_decode": True})
    @patch("src.core.extract_frames.resolve_sampling_fps", return_value=2.0)
    @patch("src.core.extract_frames.get_video_duration_seconds", return_value=10.0)
    def test_stream_frames_skips_d3d11va_for_10bit_without_nvidia(
        self,
        _mock_duration,
        _mock_resolve_fps,
        _mock_load_config,
        _mock_enabled,
        _mock_probe,
        _mock_nvidia,
        _mock_stream_info,
        mock_stream,
    ):
        mock_stream.return_value = iter([])

        list(stream_frames_with_ffmpeg("D:/video.mkv"))

        mock_stream.assert_called_once()
        self.assertEqual(mock_stream.call_args.kwargs["decode_backend"], "cpu")

    @patch("src.core.extract_frames._stream_rawvideo_frames")
    @patch(
        "src.core.extract_frames.get_video_stream_info",
        return_value={"pix_fmt": "yuv420p10le", "profile": "main 10", "bits_per_raw_sample": 10},
    )
    @patch("src.core.extract_frames.system_has_nvidia_gpu", return_value=True)
    @patch("src.core.extract_frames.ffmpeg_supports_d3d11va", return_value=True)
    @patch("src.core.extract_frames.is_experimental_hw_decode_enabled", return_value=True)
    @patch("src.core.extract_frames.load_config", return_value={"fps": 1, "experimental_hw_decode": True})
    @patch("src.core.extract_frames.resolve_sampling_fps", return_value=2.0)
    @patch("src.core.extract_frames.get_video_duration_seconds", return_value=10.0)
    def test_stream_frames_uses_d3d11va_p010_for_10bit_on_nvidia(
        self,
        _mock_duration,
        _mock_resolve_fps,
        _mock_load_config,
        _mock_enabled,
        _mock_probe,
        _mock_nvidia,
        _mock_stream_info,
        mock_stream,
    ):
        mock_stream.return_value = iter([])

        list(stream_frames_with_ffmpeg("D:/video.mkv"))

        self.assertEqual(mock_stream.call_args.kwargs["decode_backend"], "d3d11va_p010")

    @patch("src.core.extract_frames.get_ffmpeg_path", return_value="ffmpeg")
    def test_build_d3d11va_10bit_command_uses_p010_download(self, _mock_ffmpeg):
        command = _build_d3d11va_extract_command("D:/video.mkv", 1.5, ten_bit=True)

        self.assertIn("-hwaccel", command)
        self.assertIn("d3d11va", command)
        self.assertIn(
            "hwdownload,format=p010le,format=yuv420p,fps=1.500000,scale=224:224:flags=fast_bilinear",
            command,
        )

    @patch("src.core.extract_frames.get_ffmpeg_path", return_value="ffmpeg")
    def test_build_d3d11va_command_includes_hwaccel_and_hwdownload(self, _mock_ffmpeg):
        command = _build_d3d11va_extract_command("D:/video.mp4", 1.5)

        self.assertIn("-hwaccel", command)
        self.assertIn("d3d11va", command)
        self.assertIn("hwdownload,format=nv12,fps=1.500000,scale=224:224:flags=fast_bilinear", command)

    @patch("src.core.extract_frames.get_ffmpeg_path", return_value="ffmpeg")
    def test_build_cpu_command_unchanged(self, _mock_ffmpeg):
        command = _build_cpu_extract_command("D:/video.mp4", 1.5)

        self.assertNotIn("-hwaccel", command)
        self.assertIn("fps=1.500000,scale=224:224:flags=fast_bilinear", command)


class VideoProbeTests(unittest.TestCase):
    @patch("src.media.probe.get_ffprobe_path", return_value="ffprobe")
    @patch("src.media.probe.subprocess.run")
    def test_get_video_stream_info_reads_ffprobe_json(self, mock_run, _mock_ffprobe):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"streams":[{"width":1920,"height":1080}],"format":{"duration":"12.5"}}',
        )

        info = get_video_stream_info("D:/video.mp4")

        self.assertEqual(info["width"], 1920)
        self.assertEqual(info["height"], 1080)
        self.assertEqual(info["duration"], 12.5)

    @patch("src.media.probe._probe_video_duration_with_opencv", return_value=8.0)
    @patch("src.media.probe.get_video_stream_info", return_value={"width": None, "height": None, "duration": None})
    def test_get_video_duration_seconds_falls_back_when_ffprobe_unavailable(self, _mock_info, mock_fallback):
        duration = get_video_duration_seconds("D:/video.mp4")

        self.assertEqual(duration, 8.0)
        mock_fallback.assert_called_once_with("D:/video.mp4")

    @patch("src.media.probe.get_video_stream_info", return_value={"width": 1920, "height": 1080, "duration": None})
    def test_has_readable_video_stream_prefers_ffprobe_dimensions(self, _mock_info):
        self.assertTrue(has_readable_video_stream("D:/video.mp4"))

    @patch(
        "src.media.probe._probe_video_stream_with_opencv",
        return_value={"width": 1280, "height": 720, "duration": 5.0},
    )
    @patch("src.media.probe.get_video_stream_info", return_value={"width": None, "height": None, "duration": None})
    def test_has_readable_video_stream_falls_back_to_opencv_dimensions(self, _mock_info, _mock_probe):
        self.assertTrue(has_readable_video_stream("D:/video.mp4"))


if __name__ == "__main__":
    unittest.main()
