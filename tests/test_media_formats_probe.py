"""Tests for video format whitelist and ffprobe duration picking."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from src.media.formats import (
    VIDEO_EXTS,
    is_supported_video_path,
    is_transport_like_video_path,
    needs_seekable_preview_proxy,
)
from src.media import probe as probe_mod


class VideoFormatsTests(unittest.TestCase):
    def test_new_containers_are_whitelisted(self):
        for ext in (".m4v", ".mpg", ".mpeg", ".ts", ".m2ts", ".mts"):
            self.assertIn(ext, VIDEO_EXTS)
            self.assertTrue(is_supported_video_path(f"D:/lib/clip{ext}"))

    def test_transport_like_detection(self):
        self.assertTrue(is_transport_like_video_path("a.ts"))
        self.assertTrue(is_transport_like_video_path("a.M2TS"))
        self.assertTrue(is_transport_like_video_path("a.mpeg"))
        self.assertFalse(is_transport_like_video_path("a.mp4"))
        self.assertFalse(is_transport_like_video_path("a.mkv"))

    def test_seekable_proxy_needed_for_mpeg_program_streams(self):
        self.assertTrue(needs_seekable_preview_proxy("a.mpg"))
        self.assertTrue(needs_seekable_preview_proxy("a.MPEG"))
        self.assertFalse(needs_seekable_preview_proxy("a.mp4"))
        self.assertFalse(needs_seekable_preview_proxy("a.ts"))
        self.assertFalse(needs_seekable_preview_proxy("a.m2ts"))


class ProbeDurationTests(unittest.TestCase):
    @patch("src.media.probe.get_ffprobe_path", return_value="ffprobe")
    @patch("src.media.probe.subprocess.run")
    def test_prefers_stream_duration_when_format_missing(self, mock_run, _mock_path):
        mock_run.return_value = Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "streams": [
                        {
                            "width": 1920,
                            "height": 1080,
                            "codec_name": "h264",
                            "pix_fmt": "yuv420p",
                            "duration": "123.5",
                        }
                    ],
                    "format": {},
                }
            ),
        )
        info = probe_mod.get_video_stream_info(r"D:\lib\show.ts")
        self.assertEqual(info["duration"], 123.5)
        self.assertEqual(info["width"], 1920)
        cmd = mock_run.call_args.args[0]
        self.assertIn("-analyzeduration", cmd)
        self.assertIn("100M", cmd)

    @patch("src.media.probe.get_ffprobe_path", return_value="ffprobe")
    @patch("src.media.probe.subprocess.run")
    def test_mp4_uses_smaller_probe_window(self, mock_run, _mock_path):
        mock_run.return_value = Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "streams": [{"width": 640, "height": 360, "codec_name": "h264"}],
                    "format": {"duration": "10.0"},
                }
            ),
        )
        info = probe_mod.get_video_stream_info(r"D:\lib\clip.mp4")
        self.assertEqual(info["duration"], 10.0)
        cmd = mock_run.call_args.args[0]
        self.assertIn("10M", cmd)
        self.assertNotIn("100M", cmd)


if __name__ == "__main__":
    unittest.main()
