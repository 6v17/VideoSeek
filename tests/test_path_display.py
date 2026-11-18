"""Tests for video_display_name."""

from __future__ import annotations

import unittest

from src.app.path_display import readable_media_location, video_display_name
from src.services.clip_export_service import suggested_export_clip_name


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

    def test_encoded_basename_without_url(self):
        self.assertEqual(video_display_name("%E4%B8%AD%E6%96%87.mp4"), "中文.mp4")

    def test_readable_location_unquotes_the_path(self):
        url = "http://192.168.1.4:18080/videos/lib1/%E4%B8%AD%E6%96%87.mp4"
        self.assertEqual(
            readable_media_location(url),
            "http://192.168.1.4:18080/videos/lib1/中文.mp4",
        )

    def test_export_name_decodes_a_team_play_url(self):
        url = (
            "http://192.168.1.8:18080/videos/lib1/"
            "%E9%81%AD%E5%88%B0%E6%B5%81%E6%94%BE%E7%9A%84%E8%BD%AC%E7%94%9F"
            "%E9%87%8D%E9%AA%91%E5%A3%AB%E5%87%AD%E5%80%9F%E6%B8%B8%E6%88%8F"
            "%E7%9F%A5%E8%AF%86%E5%A4%A7%E5%BC%80%E6%97%A0%E5%8F%8C-06.mp4"
        )
        self.assertEqual(
            suggested_export_clip_name(url, 825),
            "遭到流放的转生重骑士凭借游戏知识大开无双-06_clip_000825.mp4",
        )

    def test_export_name_keeps_a_local_stem(self):
        self.assertEqual(
            suggested_export_clip_name(r"D:\libs\ep01.mp4", 12),
            "ep01_clip_000012.mp4",
        )

    def test_empty(self):
        self.assertEqual(video_display_name(""), "")
        self.assertEqual(video_display_name(None), "")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
