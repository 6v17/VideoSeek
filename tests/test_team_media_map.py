"""Unit tests for team media path → HTTP URL rewriting."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from src.services.team_media_map import absolute_path_to_play_url, build_media_mounts
from src.services.team_paths import normalize_http_base, normalize_team_mode


class TeamMediaMapTests(unittest.TestCase):
    def test_normalize_team_mode(self):
        self.assertEqual(normalize_team_mode("server"), "server")
        self.assertEqual(normalize_team_mode("host"), "server")
        self.assertEqual(normalize_team_mode("client"), "client")
        self.assertEqual(normalize_team_mode("employee"), "client")
        self.assertEqual(normalize_team_mode(""), "off")

    def test_normalize_http_base_adds_port(self):
        self.assertEqual(
            normalize_http_base("192.168.1.10", default_port=8765),
            "http://192.168.1.10:8765",
        )
        self.assertEqual(
            normalize_http_base("http://192.168.1.10:9000/", default_port=8765),
            "http://192.168.1.10:9000",
        )

    def test_build_mounts_and_play_url(self):
        from src.services.team_media_map import play_url_to_absolute_path, rewrite_team_scope_video_paths

        with tempfile.TemporaryDirectory() as tmp:
            lib = os.path.join(tmp, "library")
            os.makedirs(lib)
            nested = os.path.join(lib, "sub")
            os.makedirs(nested)
            video = os.path.join(nested, "clip.mp4")
            with open(video, "wb") as handle:
                handle.write(b"x")
            mounts = build_media_mounts([lib])
            self.assertEqual(len(mounts), 1)
            url = absolute_path_to_play_url(
                video,
                mounts,
                media_base_url="http://192.168.1.5:18080",
            )
            self.assertTrue(url.startswith("http://192.168.1.5:18080/videos/"))
            self.assertTrue(url.endswith("clip.mp4"))
            mapped = play_url_to_absolute_path(url, mounts)
            self.assertEqual(os.path.normcase(os.path.abspath(mapped)), os.path.normcase(os.path.abspath(video)))
            rewritten = rewrite_team_scope_video_paths([url], mounts=mounts)
            self.assertEqual(len(rewritten or []), 1)
            self.assertEqual(
                os.path.normcase(os.path.abspath(rewritten[0])),
                os.path.normcase(os.path.abspath(video)),
            )

    def test_library_browse_url_from_play_url(self):
        from src.services.team_media_map import absolute_path_to_library_browse_url

        browse = absolute_path_to_library_browse_url(
            "http://192.168.1.5:18080/videos/libabc12345/sub/clip.mp4",
            [],
            media_base_url="",
        )
        self.assertEqual(browse, "http://192.168.1.5:18080/videos/libabc12345/")

    def test_library_browse_url_from_path(self):
        from src.services.team_media_map import absolute_path_to_library_browse_url

        with tempfile.TemporaryDirectory() as tmp:
            lib = os.path.join(tmp, "library")
            os.makedirs(lib)
            video = os.path.join(lib, "clip.mp4")
            with open(video, "wb") as handle:
                handle.write(b"x")
            mounts = build_media_mounts([lib])
            browse = absolute_path_to_library_browse_url(
                video,
                mounts,
                media_base_url="http://192.168.1.5:18080",
            )
            self.assertEqual(browse, f"http://192.168.1.5:18080{mounts[0]['url_prefix']}")


if __name__ == "__main__":
    unittest.main()
