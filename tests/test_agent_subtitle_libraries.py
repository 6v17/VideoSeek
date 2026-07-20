import unittest
from unittest.mock import patch

from src.services.agent_library_service import (
    list_agent_subtitle_libraries,
    list_agent_subtitle_videos,
)


class AgentSubtitleLibraryServiceTests(unittest.TestCase):
    @patch("src.storage.lance_dialogue_search.get_dialogue_index_stats")
    @patch("src.storage.config_store.get_dialogue_search_scope_mode", return_value="all")
    @patch("src.services.subtitle_library_service.list_subtitle_search_scope_entries")
    @patch("src.services.subtitle_library_service.list_subtitle_libraries")
    def test_list_agent_subtitle_libraries(self, mock_libs, mock_entries, _scope, mock_stats):
        mock_libs.return_value = {
            "D:/Subs": {"index_state": "ready", "files": {"a.mp4": {"vid": "v1"}}},
        }
        mock_entries.return_value = [
            {
                "library_path": "D:/Subs",
                "video_path": "D:/Subs/a.mp4",
                "video_rel_path": "a.mp4",
                "video_id": "v1",
                "has_transcript": True,
                "source_exists": True,
                "asset_state": "ready",
            },
            {
                "library_path": "D:/Subs",
                "video_path": "D:/Subs/b.mp4",
                "video_rel_path": "b.mp4",
                "video_id": "v2",
                "has_transcript": False,
                "source_exists": True,
                "asset_state": "missing_asset",
            },
        ]
        mock_stats.return_value = {
            "dialogue_index_ready": True,
            "dialogue_indexed_videos": 1,
            "dialogue_rows": 9,
        }
        payload = list_agent_subtitle_libraries()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["meta"]["kind"], "subtitle")
        self.assertEqual(payload["meta"]["dialogue_rows"], 9)
        lib = payload["libraries"][0]
        self.assertEqual(lib["library_path"], "D:/Subs")
        self.assertEqual(lib["video_count_total"], 2)
        self.assertEqual(lib["video_count_subtitle_ready"], 1)
        self.assertEqual(lib["index_state"], "partial")
        self.assertTrue(lib["searchable"])

    @patch("src.services.subtitle_library_service.list_subtitle_search_scope_entries")
    @patch("src.services.subtitle_library_service.list_subtitle_libraries")
    def test_list_agent_subtitle_videos_ready_only(self, mock_libs, mock_entries):
        mock_libs.return_value = {"D:/Subs": {"files": {}}}
        mock_entries.return_value = [
            {
                "library_path": "D:/Subs",
                "video_path": "D:/Subs/a.mp4",
                "video_rel_path": "a.mp4",
                "video_id": "v1",
                "has_transcript": True,
                "source_exists": True,
                "asset_state": "ready",
            },
            {
                "library_path": "D:/Subs",
                "video_path": "D:/Subs/b.mp4",
                "video_rel_path": "b.mp4",
                "video_id": "v2",
                "has_transcript": False,
                "source_exists": True,
                "asset_state": "missing_asset",
            },
        ]
        payload = list_agent_subtitle_videos(ready_only=True)
        self.assertEqual(len(payload["videos"]), 1)
        self.assertTrue(payload["videos"][0]["has_transcript"])
        all_payload = list_agent_subtitle_videos(ready_only=False)
        self.assertEqual(len(all_payload["videos"]), 2)

    @patch("src.services.subtitle_library_service.list_subtitle_libraries", return_value={})
    def test_list_agent_subtitle_videos_unknown_library(self, _libs):
        with self.assertRaises(KeyError):
            list_agent_subtitle_videos("D:/missing")


if __name__ == "__main__":
    unittest.main()
