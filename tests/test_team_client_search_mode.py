"""Tests for team-client hit reconstruction / search_mode forwarding."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.services.team_client_search import _team_hit_time_range
from src.web.agent_api.schemas import AgentSearchRequest


class TeamHitTimeRangeTests(unittest.TestCase):
    def test_prefers_clip_window_raw_times(self):
        start, end = _team_hit_time_range(
            {
                "start_sec": 7.0,
                "end_sec": 13.0,
                "clip_window": {"raw_start_sec": 10.0, "raw_end_sec": 10.0},
            }
        )
        self.assertEqual(start, 10.0)
        self.assertEqual(end, 10.0)

    def test_falls_back_to_start_end(self):
        start, end = _team_hit_time_range({"start_sec": 3.0, "end_sec": 8.0})
        self.assertEqual(start, 3.0)
        self.assertEqual(end, 8.0)


class AgentSearchModeAliasTests(unittest.TestCase):
    @patch("src.web.agent_api.search.resolve_effective_search_scope", return_value=(None, None))
    @patch("src.web.agent_api.search.resolve_search_query_inputs")
    @patch("src.web.agent_api.health.get_search_mode", return_value="chunk")
    def test_search_mode_alias_beats_server_default(
        self,
        _mock_default_mode,
        mock_query_inputs,
        _mock_scope,
    ):
        from src.web.agent_api.search import _resolve_agent_search_inputs

        mock_query_inputs.return_value = {
            "preset": None,
            "preset_id": None,
            "query_label": "cat",
            "query_data": "cat",
            "query_type": "text",
            "is_text": True,
            "has_image": False,
            "query_vector": None,
            "default_top_k": 20,
            "default_min_score": None,
            "preset_scope_video_paths": None,
            "pixel_query_data": None,
        }
        body = AgentSearchRequest(query="cat", query_type="text", search_mode="frame")
        resolved = _resolve_agent_search_inputs(body)
        self.assertEqual(resolved.get("mode"), "frame")


if __name__ == "__main__":
    unittest.main()
