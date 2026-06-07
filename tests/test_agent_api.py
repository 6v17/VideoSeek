import os
import unittest
from unittest.mock import patch

import src.storage.config_store as config_store_module
from src.domain.search_hit import SearchHit
from src.services.search_scope import resolve_explicit_scope_library_paths
from src.services.search_request_service import default_agent_image_precision_mode
from src.web.agent_api import (
    AgentBatchSearchRequest,
    AgentSearchRequest,
    AgentSearchScope,
    _agent_timeout_settings,
    _batch_requests_precise_mode,
    _hits_to_payload,
    _resolve_batch_timeout_sec,
    _resolve_search_timeout_sec,
    api_error_payload,
    build_health_payload,
    execute_agent_batch_search,
    execute_agent_search,
    get_agent_search_preset,
    list_agent_search_presets,
    _clamp_top_k,
    _expand_image_folder,
    _filter_hits,
    _hits_to_payload,
)


class AgentApiHelperTests(unittest.TestCase):
    def test_api_error_payload_shape(self):
        payload = api_error_payload("index_not_ready", "sync first")
        self.assertEqual(payload["api_version"], "1")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "index_not_ready")

    def test_hits_to_payload_stable_fields(self):
        payload = _hits_to_payload(
            [SearchHit(1.0, 2.0, 0.9, "D:/a.mp4"), SearchHit(3.0, 3.0, 0.5, "D:/b.mp4")],
            mode="chunk",
            expand_frame_hits=False,
            pad_before_sec=3.0,
            pad_after_sec=3.0,
        )
        self.assertEqual(payload[0]["rank"], 1)
        self.assertEqual(payload[0]["start_sec"], 1.0)
        self.assertEqual(payload[0]["end_sec"], 2.0)
        self.assertEqual(payload[0]["video_path"], "D:/a.mp4")
        self.assertIn("score", payload[0])

    def test_filter_hits_min_score(self):
        hits = [
            SearchHit(0.0, 1.0, 0.2, "a.mp4"),
            SearchHit(1.0, 2.0, 0.8, "b.mp4"),
        ]
        filtered = _filter_hits(hits, 0.5)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].video_path, "b.mp4")

    def test_clamp_top_k(self):
        with patch("src.web.agent_api.get_search_top_k", return_value=20):
            self.assertEqual(_clamp_top_k(None), 20)
            self.assertEqual(_clamp_top_k(3), 3)
            self.assertEqual(_clamp_top_k(999), 200)
            self.assertEqual(_clamp_top_k("bad"), 20)

    @patch.object(config_store_module, "get_search_scope_video_paths", return_value=[])
    @patch.object(config_store_module, "get_search_scope_library_paths", return_value=["D:/saved_lib"])
    @patch.object(config_store_module, "get_search_scope_mode", return_value="selected")
    def test_resolve_scope_library_paths_use_saved_scope(self, _mock_mode, _mock_paths, _mock_videos):
        scope = AgentSearchScope(use_saved_scope=True)
        resolved = resolve_explicit_scope_library_paths(scope)
        self.assertEqual(resolved, ["D:/saved_lib"])

    def test_resolve_scope_library_paths_explicit_wins(self):
        scope = AgentSearchScope(
            library_paths=["D:/explicit"],
            use_saved_scope=True,
        )
        resolved = resolve_explicit_scope_library_paths(scope)
        self.assertEqual(resolved, ["D:/explicit"])

    @patch("src.web.agent_api.load_config")
    def test_agent_timeout_settings_from_config(self, mock_load_config):
        mock_load_config.return_value = {
            "agent_api_search_timeout_fast_sec": 75,
            "agent_api_search_timeout_precise_sec": 240,
            "agent_api_batch_timeout_sec": 900,
        }
        timeouts = _agent_timeout_settings()
        self.assertEqual(timeouts["search_timeout_fast_sec"], 75.0)
        self.assertEqual(timeouts["search_timeout_precise_sec"], 240.0)
        self.assertEqual(timeouts["batch_timeout_sec"], 900.0)

    @patch("src.services.search_request_service.load_config")
    def test_default_image_precision_mode(self, mock_load_config):
        mock_load_config.return_value = {"agent_api_default_image_precision": "precise"}
        self.assertEqual(default_agent_image_precision_mode(), "precise")

    @patch("src.web.agent_api.load_config")
    @patch("src.web.agent_api.os.path.isfile", return_value=True)
    def test_resolve_search_timeout_precise(self, _mock_isfile, mock_load_config):
        mock_load_config.return_value = {
            "agent_api_search_timeout_fast_sec": 90,
            "agent_api_search_timeout_precise_sec": 200,
        }
        body = AgentSearchRequest(
            query="D:/ref.png",
            query_type="image_path",
            search_precision_mode="precise",
        )
        self.assertEqual(_resolve_search_timeout_sec(body), 200.0)

    @patch("src.web.agent_api.load_config")
    def test_resolve_batch_timeout_scales_with_query_count(self, mock_load_config):
        mock_load_config.return_value = {
            "agent_api_search_timeout_fast_sec": 90,
            "agent_api_search_timeout_precise_sec": 180,
            "agent_api_batch_timeout_sec": 1200,
        }
        body = AgentBatchSearchRequest(
            queries=[
                AgentSearchRequest(query="a", query_type="text"),
                AgentSearchRequest(query="b", query_type="text"),
            ],
        )
        timeout = _resolve_batch_timeout_sec(body)
        self.assertGreaterEqual(timeout, 1200.0)
        self.assertFalse(_batch_requests_precise_mode(body))

    @patch("src.web.agent_api.load_config")
    @patch("src.web.agent_api.os.path.isfile", return_value=True)
    def test_batch_precise_mode_detected(self, _mock_isfile, mock_load_config):
        mock_load_config.return_value = {
            "agent_api_search_timeout_fast_sec": 90,
            "agent_api_search_timeout_precise_sec": 180,
            "agent_api_batch_timeout_sec": 1200,
        }
        body = AgentBatchSearchRequest(
            queries=[
                AgentSearchRequest(
                    query="D:/ref.png",
                    query_type="image_path",
                    search_precision_mode="precise",
                ),
            ],
        )
        self.assertTrue(_batch_requests_precise_mode(body))
        timeout = _resolve_batch_timeout_sec(body)
        self.assertGreaterEqual(timeout, 180.0)

    @patch("src.web.agent_api._index_snapshot")
    def test_build_health_payload_includes_timeout_fields(self, mock_snapshot):
        mock_snapshot.return_value = {
            "index_ready": True,
            "index_stale": False,
            "global_index_state": "fresh",
            "vector_count": 10,
            "indexed_video_paths": 1,
            "frame_vector_count": 10,
            "chunk_vector_count": 0,
            "search_index_schema_version": 1,
            "library_indexes_upgrade_needed": False,
            "library_index_count": 0,
            "library_indexes_ready": 0,
            "library_indexes_stale": 0,
        }
        payload = build_health_payload()
        self.assertEqual(payload["search_timeout_sec"], 90)
        self.assertEqual(payload["search_timeout_precise_sec"], 180)
        self.assertEqual(payload["agent_api_default_image_precision"], "fast")
        self.assertEqual(payload["batch_timeout_sec"], 1200)


class AgentStarterApiTests(unittest.TestCase):
    @patch("src.web.agent_api._index_snapshot")
    def test_build_agent_starter_payload(self, mock_snapshot):
        mock_snapshot.return_value = {
            "index_ready": True,
            "index_stale": False,
            "global_index_state": "fresh",
            "vector_count": 10,
            "indexed_video_paths": 1,
            "frame_vector_count": 10,
            "chunk_vector_count": 0,
            "search_index_schema_version": 1,
            "library_indexes_upgrade_needed": False,
            "library_index_count": 0,
            "library_indexes_ready": 0,
            "library_indexes_stale": 0,
        }
        from src.services.agent_starter_service import build_agent_starter_payload

        health = build_health_payload()
        payload = build_agent_starter_payload("http://127.0.0.1:8765", health, locale="zh")
        self.assertTrue(payload["ok"])
        self.assertIn("starter_text", payload)
        self.assertIn("/api/v1/libraries", payload["starter_text"])
        self.assertIn("search_presets", payload["starter_text"])
        self.assertIn("/api/v1/agent-doc", payload["starter_text"])
        self.assertLess(payload["meta"]["line_count"], 120)


class AgentDocApiTests(unittest.TestCase):
    def _sample_doc_payload(self):
        return {
            "api_version": "1",
            "ok": True,
            "content": "# Agent doc\n",
            "full_doc_rel": "docs/for-agents.md",
            "full_doc_path": "D:/Release/main.dist/docs/for-agents.md",
            "meta": {"line_count": 2, "byte_size": 12, "doc_on_disk": True},
        }

    @patch("src.web.agent_api.build_agent_doc_payload")
    def test_agent_doc_json(self, mock_build):
        mock_build.return_value = self._sample_doc_payload()
        from fastapi.testclient import TestClient
        from src.web.agent_api import AgentApiService

        client = TestClient(AgentApiService(host="127.0.0.1", port=8765).app)
        response = client.get("/api/v1/agent-doc")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("# Agent doc", payload["content"])

    @patch("src.web.agent_api.build_agent_doc_payload")
    def test_agent_doc_text(self, mock_build):
        mock_build.return_value = self._sample_doc_payload()
        from fastapi.testclient import TestClient
        from src.web.agent_api import AgentApiService

        client = TestClient(AgentApiService(host="127.0.0.1", port=8765).app)
        response = client.get("/api/v1/agent-doc", params={"format": "text"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/markdown", response.headers.get("content-type", ""))
        self.assertIn("# Agent doc", response.text)
        self.assertIn(
            "D:/Release/main.dist/docs/for-agents.md",
            response.headers.get("X-VideoSeek-Doc-Path", ""),
        )

    @patch("src.web.agent_api.build_agent_doc_payload")
    def test_agent_doc_not_found(self, mock_build):
        mock_build.side_effect = FileNotFoundError("docs/for-agents.md")
        from fastapi.testclient import TestClient
        from src.web.agent_api import AgentApiService

        client = TestClient(AgentApiService(host="127.0.0.1", port=8765).app)
        response = client.get("/api/v1/agent-doc")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "doc_not_found")


class AgentApiSearchTests(unittest.TestCase):
    @patch("src.web.agent_api._index_snapshot")
    @patch("src.web.agent_api.run_search")
    def test_execute_agent_search_text_frame(self, mock_run_search, mock_snapshot):
        mock_snapshot.return_value = {
            "index_ready": True,
            "global_index_state": "fresh",
        }
        mock_run_search.return_value = [SearchHit(10.0, 10.0, 0.7, "D:/clip.mp4")]
        body = AgentSearchRequest(
            query="足球进球",
            query_type="text",
            top_k=5,
            mode="frame",
            client_request_id="beat-01",
        )
        payload = execute_agent_search(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["query"], "足球进球")
        self.assertEqual(payload["mode"], "frame")
        self.assertEqual(payload["client_request_id"], "beat-01")
        self.assertEqual(len(payload["hits"]), 1)
        mock_run_search.assert_called_once()

    @patch("src.web.agent_api._index_snapshot")
    @patch("src.web.agent_api.run_chunk_search")
    def test_execute_agent_search_chunk_mode(self, mock_chunk_search, mock_snapshot):
        mock_snapshot.return_value = {
            "index_ready": True,
            "global_index_state": "fresh",
        }
        mock_chunk_search.return_value = [SearchHit(1.0, 4.0, 0.6, "D:/clip.mp4")]
        body = AgentSearchRequest(query="product close-up", mode="chunk")
        payload = execute_agent_search(body)
        self.assertEqual(payload["mode"], "chunk")
        self.assertEqual(payload["hits"][0]["end_sec"], 4.0)
        mock_chunk_search.assert_called_once()


class AgentApiHealthTests(unittest.TestCase):
    @patch("src.web.agent_api.get_search_scope_mode", return_value="all")
    @patch("src.web.agent_api._build_ffmpeg_info")
    @patch("src.web.agent_api._index_snapshot")
    @patch("src.web.agent_api.get_active_embedding_spec")
    @patch("src.services.library_service.list_libraries")
    @patch("src.web.agent_api.get_search_mode")
    def test_build_health_payload(self, mock_mode, mock_libraries, mock_spec, mock_snapshot, mock_ffmpeg, _mock_scope_mode):
        mock_mode.return_value = "frame"
        mock_libraries.return_value = {"D:/lib": {"files": {"a": {}, "b": {}}}}
        mock_spec.return_value = {
            "model_id": "clip_onnx_default",
            "provider": "clip_onnx",
            "embedding_space": "clip_onnx_default",
            "dimension": 512,
            "metric": "ip",
        }
        mock_snapshot.return_value = {
            "index_ready": True,
            "index_stale": False,
            "global_index_state": "fresh",
            "vector_count": 100,
            "indexed_video_paths": 3,
            "frame_index_ready": True,
            "chunk_index_ready": True,
            "frame_vector_count": 80,
            "chunk_vector_count": 20,
            "search_index_schema_version": 2,
            "library_indexes_upgrade_needed": False,
            "library_index_count": 2,
            "library_indexes_ready": 2,
            "library_indexes_stale": 0,
        }
        mock_ffmpeg.return_value = {
            "ffmpeg_available": True,
            "ffmpeg_path": "D:/VideoSeek/bin/ffmpeg.exe",
            "ffmpeg_source": "managed",
        }
        payload = build_health_payload()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["index_ready"])
        self.assertEqual(payload["video_count"], 2)
        self.assertEqual(payload["dimension"], 512)
        self.assertIn("index_id", payload)
        self.assertTrue(payload["capabilities"]["text_search"])
        self.assertTrue(payload["capabilities"]["chunk_search"])
        self.assertTrue(payload["capabilities"]["search_presets"])
        self.assertTrue(payload["capabilities"]["local_ffmpeg_clip"])
        self.assertEqual(payload["ffmpeg"]["ffmpeg_path"], "D:/VideoSeek/bin/ffmpeg.exe")
        self.assertEqual(payload["search_index_schema_version"], 2)
        self.assertEqual(payload["library_indexes_ready"], 2)


class AgentApiBatchTests(unittest.TestCase):
    @patch("src.web.agent_api.execute_agent_search")
    @patch("src.web.agent_api._index_snapshot")
    def test_execute_agent_batch_search_mixed(self, mock_snapshot, mock_search):
        mock_snapshot.return_value = {"index_ready": True, "global_index_state": "fresh"}
        mock_search.side_effect = [
            {
                "api_version": "1",
                "ok": True,
                "query": "D:/a.png",
                "query_type": "image_path",
                "mode": "chunk",
                "client_request_id": "a",
                "hits": [],
                "meta": {},
            },
            ValueError("bad"),
        ]
        body = AgentBatchSearchRequest(
            queries=[
                AgentSearchRequest(query="D:/a.png", query_type="image_path", client_request_id="a"),
                AgentSearchRequest(query="bad", query_type="text", client_request_id="b"),
            ],
            mode="chunk",
            continue_on_error=True,
        )
        payload = execute_agent_batch_search(body)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["meta"]["succeeded"], 1)
        self.assertEqual(payload["meta"]["failed"], 1)
        self.assertEqual(len(payload["results"]), 2)

    def test_expand_image_folder_sorted(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "b.png"), "wb").close()
            open(os.path.join(tmp, "a.jpg"), "wb").close()
            open(os.path.join(tmp, "skip.txt"), "w", encoding="utf-8").close()
            items = _expand_image_folder(tmp)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0].client_request_id, "a.jpg")
            self.assertEqual(items[1].client_request_id, "b.png")


class AgentApiPresetTests(unittest.TestCase):
    @patch("src.services.search_preset_service.list_presets")
    def test_list_agent_search_presets(self, mock_list_presets):
        mock_list_presets.return_value = [
            {
                "id": "p1",
                "name": "Night City",
                "query": "anime night",
                "ref_files": [],
            }
        ]
        payload = list_agent_search_presets()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["meta"]["count"], 1)
        self.assertEqual(payload["presets"][0]["id"], "p1")
        self.assertEqual(payload["presets"][0]["reference_image_count"], 0)

    @patch("src.services.search_preset_service.get_preset")
    def test_get_agent_search_preset_not_found(self, mock_get_preset):
        mock_get_preset.return_value = None
        with self.assertRaises(KeyError):
            get_agent_search_preset("missing")

    @patch("src.web.agent_api.resolve_active_search_video_scope", return_value=None)
    @patch("src.web.agent_api.resolve_active_search_library_scope", return_value=["D:/saved_lib"])
    @patch("src.web.agent_api._index_snapshot")
    @patch("src.web.agent_api.run_search")
    def test_execute_agent_search_uses_active_scope_by_default(
        self,
        mock_run_search,
        mock_snapshot,
        _mock_library_scope,
        _mock_video_scope,
    ):
        mock_snapshot.return_value = {"index_ready": True, "global_index_state": "fresh"}
        mock_run_search.return_value = [SearchHit(1.0, 1.0, 0.9, "D:/clip.mp4")]
        body = AgentSearchRequest(query="goal", mode="frame")
        payload = execute_agent_search(body)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["meta"]["scope_applied"])
        kwargs = mock_run_search.call_args.kwargs
        self.assertEqual(kwargs.get("scope_library_paths"), ["D:/saved_lib"])
        self.assertIsNone(kwargs.get("scope_video_paths"))

    @patch("src.web.agent_api.resolve_active_search_video_scope", return_value=["D:/scoped.mp4"])
    @patch("src.web.agent_api._index_snapshot")
    @patch("src.web.agent_api.run_search")
    def test_execute_agent_search_uses_active_video_scope(
        self,
        mock_run_search,
        mock_snapshot,
        _mock_video_scope,
    ):
        mock_snapshot.return_value = {"index_ready": True, "global_index_state": "fresh"}
        mock_run_search.return_value = [SearchHit(1.0, 1.0, 0.9, "D:/scoped.mp4")]
        body = AgentSearchRequest(query="goal", mode="frame")
        payload = execute_agent_search(body)
        kwargs = mock_run_search.call_args.kwargs
        self.assertEqual(kwargs.get("scope_video_paths"), ["D:/scoped.mp4"])
        self.assertIsNone(kwargs.get("scope_library_paths"))

    @patch("src.web.agent_api._index_snapshot")
    @patch("src.web.agent_api.run_search")
    def test_execute_agent_search_passes_search_precision_mode(self, mock_run_search, mock_snapshot):
        mock_snapshot.return_value = {"index_ready": True, "global_index_state": "fresh"}
        mock_run_search.return_value = [SearchHit(1.0, 1.0, 0.9, "D:/clip.mp4")]
        with patch("src.web.agent_api.os.path.isfile", return_value=True):
            body = AgentSearchRequest(
                query="D:/ref.png",
                query_type="image_path",
                search_precision_mode="precise",
                mode="frame",
            )
            payload = execute_agent_search(body)
        self.assertEqual(payload["meta"]["search_precision_mode"], "precise")
        kwargs = mock_run_search.call_args.kwargs
        self.assertEqual(kwargs.get("search_precision_mode"), "precise")

    @patch("src.web.agent_api.resolve_active_search_library_scope", return_value=["D:/lib"])
    @patch("src.web.agent_api.resolve_active_search_video_scope", return_value=None)
    @patch("src.services.search_preset_service.build_preset_search_plan")
    @patch("src.web.agent_api._index_snapshot")
    @patch("src.web.agent_api.run_search")
    def test_execute_agent_search_by_preset_id(
        self,
        mock_run_search,
        mock_snapshot,
        mock_build_plan,
        _mock_video_scope,
        _mock_scope,
    ):
        import numpy as np

        mock_snapshot.return_value = {"index_ready": True, "global_index_state": "fresh"}
        mock_run_search.return_value = [SearchHit(10.0, 10.0, 0.7, "D:/clip.mp4")]
        mock_build_plan.return_value = {
            "preset": {"id": "p1", "name": "Night City", "query": "anime night"},
            "query_vector": np.array([[0.1, 0.2]], dtype=np.float32),
            "search_mode": "frame",
            "top_k": 12,
            "min_score": None,
            "is_text": True,
            "has_image": False,
            "query_data": "anime night",
            "scope_video_paths": None,
            "pixel_query_data": None,
        }
        body = AgentSearchRequest(preset_id="p1", mode="frame")
        payload = execute_agent_search(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["preset_id"], "p1")
        self.assertEqual(payload["preset_name"], "Night City")
        self.assertEqual(payload["query"], "Night City")
        kwargs = mock_run_search.call_args.kwargs
        self.assertIsNotNone(kwargs.get("query_vector"))
        self.assertEqual(kwargs.get("scope_library_paths"), ["D:/lib"])

    @patch("src.services.search_preset_service.build_preset_search_plan")
    @patch("src.web.agent_api._index_snapshot")
    @patch("src.web.agent_api.run_search")
    def test_execute_agent_search_preset_uses_video_scope_and_pixel_query(
        self,
        mock_run_search,
        mock_snapshot,
        mock_build_plan,
    ):
        import numpy as np

        mock_snapshot.return_value = {"index_ready": True, "global_index_state": "fresh"}
        mock_run_search.return_value = [SearchHit(10.0, 10.0, 0.7, "D:/clip.mp4")]
        mock_build_plan.return_value = {
            "preset": {"id": "p2", "name": "Ref Shot", "query": ""},
            "query_vector": np.array([[0.1, 0.2]], dtype=np.float32),
            "search_mode": "frame",
            "top_k": 8,
            "min_score": None,
            "is_text": False,
            "has_image": True,
            "query_data": "D:/ref.png",
            "scope_video_paths": ["D:/clip.mp4"],
            "pixel_query_data": "D:/ref.png",
        }
        body = AgentSearchRequest(preset_id="p2", mode="frame", search_precision_mode="precise")
        payload = execute_agent_search(body)
        self.assertTrue(payload["ok"])
        kwargs = mock_run_search.call_args.kwargs
        self.assertEqual(kwargs.get("scope_video_paths"), ["D:/clip.mp4"])
        self.assertIsNone(kwargs.get("scope_library_paths"))
        self.assertEqual(kwargs.get("pixel_query_data"), "D:/ref.png")
        self.assertEqual(kwargs.get("search_precision_mode"), "precise")

    def test_execute_agent_search_rejects_query_and_preset(self):
        body = AgentSearchRequest(query="test", preset_id="p1")
        with self.assertRaises(ValueError):
            execute_agent_search(body)

    def test_preview_anchor_sec_requires_single_video_scope(self):
        body = AgentSearchRequest(
            query="D:/crop.png",
            query_type="image_path",
            preview_anchor_sec=64.0,
            scope=AgentSearchScope(video_paths=["D:/a.mp4", "D:/b.mp4"]),
        )
        with patch("src.web.agent_api._resolve_agent_search_inputs") as mock_resolve:
            mock_resolve.return_value = {
                "has_image": True,
                "scope_video_paths": ["D:/a.mp4", "D:/b.mp4"],
                "mode": "frame",
                "top_k": 3,
                "min_score": None,
                "search_precision_mode": "fast",
                "query_data": "D:/crop.png",
                "query_vector": None,
                "pixel_query_data": None,
                "query_label": "crop",
                "query_type": "image_path",
                "is_text": False,
                "preset_id": None,
                "preset": None,
                "scope_library_paths": None,
            }
            with self.assertRaises(ValueError):
                execute_agent_search(body)

    @patch("src.web.agent_api.run_search")
    @patch("src.web.agent_api._resolve_agent_search_inputs")
    @patch("src.web.agent_api._search_index_ready_for_request", return_value=True)
    @patch("src.web.agent_api._index_snapshot")
    def test_preview_anchor_sec_forces_precise_locate(
        self,
        mock_snapshot,
        _mock_ready,
        mock_resolve,
        mock_run_search,
    ):
        mock_snapshot.return_value = {
            "index_ready": True,
            "global_index_state": "fresh",
            "library_indexes_upgrade_needed": False,
            "search_index_schema_version": 2,
        }
        mock_resolve.return_value = {
            "has_image": True,
            "scope_video_paths": ["D:/clip.mp4"],
            "mode": "frame",
            "top_k": 1,
            "min_score": None,
            "search_precision_mode": "fast",
            "query_data": "D:/crop.png",
            "query_vector": None,
            "pixel_query_data": "D:/crop.png",
            "query_label": "crop",
            "query_type": "image_path",
            "is_text": False,
            "preset_id": None,
            "preset": None,
            "scope_library_paths": None,
        }
        mock_run_search.return_value = [SearchHit(64.0, 64.0, 0.88, "D:/clip.mp4")]
        body = AgentSearchRequest(
            query="D:/crop.png",
            query_type="image_path",
            preview_anchor_sec=64.0,
            scope=AgentSearchScope(video_paths=["D:/clip.mp4"]),
            top_k=1,
        )
        payload = execute_agent_search(body)
        self.assertTrue(payload["ok"])
        kwargs = mock_run_search.call_args.kwargs
        self.assertEqual(kwargs.get("preview_anchor_sec"), 64.0)
        self.assertEqual(kwargs.get("search_precision_mode"), "precise")
        self.assertTrue(payload["meta"].get("crop_locate"))

    def test_get_agent_search_telemetry_shape(self):
        with patch("src.services.search_telemetry.is_telemetry_enabled", return_value=True):
            with patch("src.services.search_telemetry.reload_telemetry_state", return_value={}):
                with patch(
                    "src.services.search_telemetry.get_telemetry_summary",
                    return_value={"crop_locate": {"total": 0}},
                ):
                    with patch(
                        "src.services.search_telemetry.format_telemetry_panel",
                        return_value="Anchor 保留率\n—",
                    ):
                        with patch(
                            "src.services.search_telemetry.get_telemetry_file_path",
                            return_value="C:/tmp/search_telemetry.json",
                        ):
                            from src.web.agent_api import get_agent_search_telemetry

                            payload = get_agent_search_telemetry(locale="zh")
        self.assertTrue(payload["ok"])
        self.assertIn("summary", payload)
        self.assertIn("panel_text", payload)
        self.assertEqual(payload["file_path"], "C:/tmp/search_telemetry.json")


if __name__ == "__main__":
    unittest.main()
