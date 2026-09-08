"""Tests for video_display_name."""

from __future__ import annotations

import unittest

from src.app.path_display import video_display_name


class VideoDisplayNameTests(unittest.TestCase):
    def test_local_path(self):
        self.assertEqual(video_display_name(r"D:\libs\clip.mp4"), "clip.mp4")
        self.assertEqual(video_display_name("D:/libs/clip.mp4"), "clip.mp4")

    def test_team_play_url_unquotes_filename(self):
        url = "http://192.168.1.2:18080/videos/libabc123/folder/%E4%B8%AD%E6%96%87%20A.mp4"
        self.assertEqual(video_display_name(url), "中文 A.mp4")

    def test_team_play_url_without_encoding(self):
        url = "http://192.168.1.2:18080/videos/lib1/a.mp4"
        self.assertEqual(video_display_name(url), "a.mp4")

    def test_empty(self):
        self.assertEqual(video_display_name(""), "")
        self.assertEqual(video_display_name(None), "")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
