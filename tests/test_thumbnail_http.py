"""Thumbnail helper tests."""

from __future__ import annotations

import unittest
from unittest import mock

from src.media.thumbnail import get_single_thumbnail


class ThumbnailHttpTests(unittest.TestCase):
    def test_http_url_skips_local_isfile_and_uses_ffmpeg(self):
        fake_frame = mock.Mock()
        fake_frame.size = 1
        with mock.patch("src.media.thumbnail._ffmpeg_capture_frame", return_value=fake_frame) as mock_ff:
            with mock.patch("src.media.thumbnail.cv2.VideoCapture") as mock_cap:
                frame = get_single_thumbnail("http://192.168.1.2:18080/videos/lib1/a.mp4", 12.5)
        self.assertIs(frame, fake_frame)
        mock_ff.assert_called_once()
        mock_cap.assert_not_called()

    def test_missing_local_file_returns_none(self):
        frame = get_single_thumbnail("D:/missing/nope.mp4", 1.0)
        self.assertIsNone(frame)


if __name__ == "__main__":
    unittest.main()
