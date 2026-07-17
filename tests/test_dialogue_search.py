import unittest
from unittest import mock

from src.domain.search_hit import SearchHit
from src.web.agent_api.schemas import AgentSearchRequest


class RunDialogueSearchTests(unittest.TestCase):
    @mock.patch("src.storage.lance_dialogue_search.get_dialogue_index_stats")
    @mock.patch("src.storage.lance_dialogue_search.search_dialogue")
    @mock.patch("src.storage.config_store.get_local_model_asset_dirs")
    def test_missing_index_returns_message(self, mock_dirs, mock_search, mock_stats):
        from src.services.search_service import run_dialogue_search

        mock_dirs.return_value = {"base_dir": "D:/tmp/profile"}
        mock_stats.return_value = {
            "dialogue_index_ready": False,
            "dialogue_indexed_videos": 0,
            "dialogue_rows": 0,
        }
        hits, message, matched_by = run_dialogue_search("スポンサー")
        self.assertEqual(hits, [])
        self.assertIn("dialogue index", message.lower())
        self.assertEqual(matched_by, "")
        mock_search.assert_not_called()

    @mock.patch("src.services.search_service.apply_search_scope", side_effect=lambda hits, **kwargs: hits)
    @mock.patch("src.storage.lance_dialogue_search.get_dialogue_index_stats")
    @mock.patch("src.storage.lance_dialogue_search.search_dialogue")
    @mock.patch("src.storage.config_store.get_local_model_asset_dirs")
    def test_keyword_hits_map_to_search_hit(self, mock_dirs, mock_search, mock_stats, _scope):
        from src.services.search_service import run_dialogue_search
        from src.storage.lance_dialogue_search import DialogueSearchHit

        mock_dirs.return_value = {"base_dir": "D:/tmp/profile"}
        mock_stats.return_value = {
            "dialogue_index_ready": True,
            "dialogue_indexed_videos": 1,
            "dialogue_rows": 2,
        }
        mock_search.return_value = {
            "matched_by": "keyword",
            "hits": [
                DialogueSearchHit(
                    video_id="v1",
                    video_path="D:/a.mp4",
                    library_path="D:/",
                    start_sec=1.0,
                    end_sec=2.0,
                    text="スポンサー",
                    language="ja",
                    score=1.0,
                    matched_by="keyword",
                )
            ],
            "message": "",
        }
        hits, message, matched_by = run_dialogue_search("スポンサー", top_k=5, match_mode="segment")
        self.assertEqual(message, "")
        self.assertEqual(matched_by, "keyword")
        self.assertEqual(len(hits), 1)
        self.assertIsInstance(hits[0], SearchHit)
        self.assertEqual(hits[0].match_kind, "dialogue")
        self.assertEqual(hits[0].matched_text, "スポンサー")
        mock_search.assert_called()
        self.assertEqual(mock_search.call_args.kwargs.get("match_mode"), "segment")


class AgentDialogueSearchTests(unittest.TestCase):
    @mock.patch("src.web.agent_api.search.run_dialogue_search")
    @mock.patch("src.storage.lance_dialogue_search.get_dialogue_index_stats")
    @mock.patch("src.web.agent_api.search._resolve_agent_search_scope")
    def test_execute_dialogue_search_ok(self, mock_scope, mock_stats, mock_run):
        from src.web.agent_api.search import execute_agent_search

        mock_scope.return_value = (None, None)
        mock_stats.return_value = {
            "dialogue_index_ready": True,
            "dialogue_indexed_videos": 1,
            "dialogue_rows": 3,
        }
        mock_run.return_value = (
            [
                SearchHit(
                    12.0,
                    15.0,
                    1.0,
                    "D:/clip.mp4",
                    match_kind="dialogue",
                    video_id="vid",
                    matched_text="スポンサー",
                )
            ],
            "",
            "keyword",
        )
        body = AgentSearchRequest(query="スポンサー", search_kind="dialogue", top_k=3)
        payload = execute_agent_search(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["search_kind"], "dialogue")
        self.assertEqual(payload["hits"][0]["matched_text"], "スポンサー")
        self.assertEqual(payload["hits"][0]["match_kind"], "dialogue")
        self.assertNotIn("message", payload)

    @mock.patch("src.web.agent_api.search.run_dialogue_search")
    @mock.patch("src.storage.lance_dialogue_search.get_dialogue_index_stats")
    @mock.patch("src.web.agent_api.search._resolve_agent_search_scope")
    def test_execute_dialogue_search_empty_message(self, mock_scope, mock_stats, mock_run):
        from src.web.agent_api.search import execute_agent_search

        mock_scope.return_value = (None, None)
        mock_stats.return_value = {
            "dialogue_index_ready": False,
            "dialogue_indexed_videos": 0,
            "dialogue_rows": 0,
        }
        mock_run.return_value = ([], "no dialogue index for active profile (build dialogue index first)", "")
        body = AgentSearchRequest(query="hello", search_kind="dialogue")
        payload = execute_agent_search(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["hits"], [])
        self.assertIn("dialogue index", payload["message"])


class HealthDialogueFieldsTests(unittest.TestCase):
    @mock.patch("src.storage.lance_dialogue_search.get_dialogue_index_stats")
    @mock.patch("src.web.agent_api.health.build_agent_understanding_health_fields", return_value={})
    @mock.patch("src.services.indexing_runtime_status.get_index_sync_status", return_value={})
    @mock.patch("src.web.agent_api.health._index_snapshot")
    @mock.patch("src.web.agent_api.health.get_active_embedding_spec")
    @mock.patch("src.web.agent_api.health.load_config", return_value={})
    def test_health_includes_dialogue_fields(
        self,
        _cfg,
        mock_spec,
        mock_snapshot,
        _sync,
        _understanding,
        mock_dialogue,
    ):
        from src.web.agent_api.health import build_health_payload

        mock_spec.return_value = {
            "model_id": "clip",
            "provider": "openai-clip",
            "embedding_space": "clip",
            "dimension": 512,
            "metric": "ip",
        }
        mock_snapshot.return_value = {
            "index_ready": True,
            "index_stale": False,
            "global_index_state": "fresh",
            "vector_count": 10,
            "indexed_video_paths": 1,
            "frame_vector_count": 10,
            "chunk_vector_count": 2,
            "search_index_schema_version": 1,
            "library_indexes_upgrade_needed": False,
            "library_index_count": 0,
            "library_indexes_ready": 0,
            "library_indexes_stale": 0,
            "frame_index_ready": True,
            "chunk_index_ready": True,
        }
        mock_dialogue.return_value = {
            "dialogue_index_ready": True,
            "dialogue_indexed_videos": 2,
            "dialogue_rows": 40,
        }
        payload = build_health_payload("frame")
        self.assertTrue(payload["dialogue_index_ready"])
        self.assertEqual(payload["dialogue_indexed_videos"], 2)
        self.assertTrue(payload["capabilities"]["dialogue_search"])


if __name__ == "__main__":
    unittest.main()
