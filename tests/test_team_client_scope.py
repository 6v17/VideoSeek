"""Tests for team client scope payload wiring."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from src.services.team_client_search import run_team_client_search


class TeamClientScopeTests(unittest.TestCase):
    def test_search_sends_video_scope(self):
        captured = {}

        def fake_post(url, payload, timeout=120.0):
            captured["url"] = url
            captured["payload"] = payload
            return {
                "ok": True,
                "hits": [
                    {
                        "play_url": "http://192.168.1.2:18080/videos/lib1/a.mp4",
                        "start_sec": 1.0,
                        "end_sec": 2.0,
                        "score": 0.5,
                    }
                ],
            }

        with mock.patch("src.services.team_client_search._post_json", side_effect=fake_post):
            hits = run_team_client_search(
                server_url="http://192.168.1.2:8765",
                query_data="巨人",
                is_text=True,
                scope_video_paths=[r"e:\素材\a.mp4"],
            )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].video_path, "http://192.168.1.2:18080/videos/lib1/a.mp4")
        scope = captured["payload"].get("scope") or {}
        self.assertEqual(scope.get("video_paths"), [r"e:\素材\a.mp4"])
        self.assertNotIn("library_paths", scope)

    def test_search_sends_library_scope_when_no_videos(self):
        captured = {}

        def fake_post(url, payload, timeout=120.0):
            captured["payload"] = payload
            return {"ok": True, "hits": []}

        with mock.patch("src.services.team_client_search._post_json", side_effect=fake_post):
            run_team_client_search(
                server_url="http://192.168.1.2:8765",
                query_data="巨人",
                is_text=True,
                scope_library_paths=[r"e:\素材"],
            )
        scope = captured["payload"].get("scope") or {}
        self.assertEqual(scope.get("library_paths"), [r"e:\素材"])

    def test_search_sends_video_discovery_enabled(self):
        captured = {}

        def fake_post(url, payload, timeout=120.0):
            captured["payload"] = payload
            return {"ok": True, "hits": []}

        with mock.patch("src.services.team_client_search._post_json", side_effect=fake_post):
            with mock.patch(
                "src.services.team_client_search._encode_image_query",
                return_value={"query_type": "image", "image_base64": "xx", "image_mime": "image/png"},
            ):
                run_team_client_search(
                    server_url="http://192.168.1.2:8765",
                    query_data="D:/q.png",
                    is_text=False,
                    search_mode="frame",
                    search_precision_mode="fast",
                    video_discovery_enabled=True,
                )
        self.assertTrue(captured["payload"].get("video_discovery_enabled"))
        self.assertEqual(captured["payload"].get("search_mode"), "frame")
        self.assertEqual(captured["payload"].get("search_precision_mode"), "fast")


if __name__ == "__main__":
    unittest.main()
