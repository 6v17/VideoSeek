import unittest
from unittest.mock import patch

from src.domain.search_hit import SearchHit
from src.web.agent_api import (
    AgentManifestRequest,
    AgentSearchRequest,
    AgentSearchScope,
    _enrich_hit_payload,
    _expand_clip_window,
    _format_timecode,
    dedupe_manifest_items,
    execute_export_manifest,
    execute_agent_search,
)


class AgentApiP0Tests(unittest.TestCase):
    def test_format_timecode(self):
        self.assertEqual(_format_timecode(3661), "01:01:01")

    def test_expand_frame_point_hit(self):
        window = _expand_clip_window(
            10.0,
            10.0,
            mode="frame",
            expand_frame_hits=True,
            pad_before_sec=3.0,
            pad_after_sec=3.0,
            video_path="D:/a.mp4",
        )
        self.assertTrue(window["padding_applied"])
        self.assertEqual(window["start_sec"], 7.0)
        self.assertEqual(window["end_sec"], 13.0)

    def test_enrich_hit_payload_fields(self):
        hit = SearchHit(100.0, 100.0, 0.5, "D:/a.mp4")
        payload = _enrich_hit_payload(
            hit,
            rank=1,
            mode="frame",
            expand_frame_hits=True,
            pad_before_sec=3.0,
            pad_after_sec=3.0,
        )
        self.assertIn("duration_sec", payload)
        self.assertIn("start_timecode", payload)
        self.assertIn("clip_window", payload)
        self.assertEqual(payload["duration_sec"], 6.0)

    @patch("src.web.agent_api._index_snapshot")
    @patch("src.web.agent_api.run_search")
    def test_scope_filters_hits(self, mock_run_search, mock_snapshot):
        mock_snapshot.return_value = {"index_ready": True, "global_index_state": "fresh"}
        mock_run_search.return_value = [SearchHit(1.0, 1.0, 0.9, "D:/keep.mp4")]
        body = AgentSearchRequest(
            query="boy",
            scope=AgentSearchScope(video_paths=["D:/keep.mp4"]),
            top_k=1,
            mode="frame",
            expand_frame_hits=False,
        )
        payload = execute_agent_search(body)
        self.assertEqual(len(payload["hits"]), 1)
        self.assertEqual(payload["hits"][0]["video_path"], "D:/keep.mp4")
        self.assertTrue(payload["meta"]["scope_applied"])
        mock_run_search.assert_called_once()
        kwargs = mock_run_search.call_args.kwargs
        self.assertEqual(kwargs.get("scope_video_paths"), ["D:/keep.mp4"])
        self.assertIsNone(kwargs.get("scope_library_paths"))

    @patch("src.web.agent_api._per_library_indexes_ready", return_value=True)
    @patch("src.web.agent_api._index_snapshot")
    @patch("src.web.agent_api.run_search")
    def test_scope_library_paths_uses_per_library_route(self, mock_run_search, mock_snapshot, _mock_ready):
        mock_snapshot.return_value = {
            "index_ready": False,
            "global_index_state": "stale",
            "search_index_schema_version": 2,
            "library_indexes_upgrade_needed": False,
        }
        mock_run_search.return_value = [SearchHit(2.0, 2.0, 0.8, "D:/lib/clip.mp4")]
        body = AgentSearchRequest(
            query="goal",
            scope=AgentSearchScope(library_paths=["D:/Videos/MyLibrary"]),
            mode="frame",
        )
        payload = execute_agent_search(body)
        self.assertEqual(len(payload["hits"]), 1)
        self.assertTrue(payload["meta"]["scope_uses_per_library_indexes"])
        kwargs = mock_run_search.call_args.kwargs
        self.assertEqual(kwargs.get("scope_library_paths"), ["D:/Videos/MyLibrary"])
        self.assertIsNone(kwargs.get("scope_video_paths"))

    def test_dedupe_manifest_items(self):
        items = [
            {"rank": 1, "video_path": "D:/a.mp4", "start_sec": 10.0, "end_sec": 15.0},
            {"rank": 2, "video_path": "D:/a.mp4", "start_sec": 11.0, "end_sec": 16.0},
            {"rank": 3, "video_path": "D:/b.mp4", "start_sec": 1.0, "end_sec": 2.0},
        ]
        deduped = dedupe_manifest_items(items, mode="chunk")
        self.assertEqual(len(deduped), 2)

    def test_export_manifest_from_sources(self):
        body = AgentManifestRequest(
            project="test",
            sources=[
                {
                    "ok": True,
                    "query": "ref.png",
                    "client_request_id": "ref.png",
                    "mode": "chunk",
                    "hits": [
                        {
                            "rank": 1,
                            "video_path": "D:/a.mp4",
                            "start_sec": 1.0,
                            "end_sec": 5.0,
                            "score": 0.7,
                            "duration_sec": 4.0,
                            "start_timecode": "00:00:01",
                            "end_timecode": "00:00:05",
                        }
                    ],
                }
            ],
            dedupe=False,
        )
        payload = execute_export_manifest(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["manifest"]["items"]), 1)
        self.assertEqual(payload["manifest"]["items"][0]["start_timecode"], "00:00:01")


if __name__ == "__main__":
    unittest.main()
