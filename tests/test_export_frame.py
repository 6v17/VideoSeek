"""Current-frame still export."""

import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from src.media.export_frame import publish_still, save_video_frame, wait_for_written_file


class SaveVideoFrameTests(unittest.TestCase):
    @patch("src.media.export_frame.os.path.getsize", return_value=12)
    @patch("src.media.export_frame.os.path.isfile", return_value=True)
    @patch("src.media.export_frame.os.makedirs")
    @patch("src.media.export_frame.subprocess.run")
    @patch("src.media.export_frame.has_ffmpeg", return_value=True)
    @patch("src.media.export_frame.get_ffmpeg_path", return_value="ffmpeg")
    def test_png_uses_accurate_seek(self, _ffmpeg, _has, run, _mkdir, _isfile, _size):
        dest = save_video_frame("clip.mp4", 12.5, os.path.join("out", "frame.png"))
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("12.150", cmd)
        self.assertEqual(cmd[cmd.index("-i") + 1], "clip.mp4")
        self.assertIn("0.350", cmd)
        self.assertIn("png", cmd)
        self.assertTrue(dest.endswith("frame.png"))

    @patch("src.media.export_frame.has_ffmpeg", return_value=False)
    def test_missing_ffmpeg_raises(self, _has):
        with self.assertRaises(RuntimeError):
            save_video_frame("clip.mp4", 1.0, "frame.png")


class DisplayedFramePublishTests(unittest.TestCase):
    def test_wait_accepts_a_finished_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "frame.png")
            with open(path, "wb") as handle:
                handle.write(b"png")
            self.assertTrue(wait_for_written_file(path, timeout_sec=1.0))

    def test_publish_converts_png_snapshot_to_jpg(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "shot.png")
            dest = os.path.join(folder, "shot.jpg")
            Image.new("RGB", (2, 2), (10, 20, 30)).save(source)
            published = publish_still(source, dest)
            self.assertTrue(published.endswith("shot.jpg"))
            self.assertTrue(os.path.isfile(dest))
            self.assertFalse(os.path.isfile(source))
