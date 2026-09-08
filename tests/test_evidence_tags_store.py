import json
import os
import tempfile
import unittest
from unittest import mock


def _sample_bundle(*, tags0=None, tags1=None, video_id="vid1") -> dict:
    return {
        "schema_version": 1,
        "video": {
            "video_id": video_id,
            "video_path": "D:/Videos/ep01.mp4",
            "video_rel_path": "ep01.mp4",
            "library_path": "D:/Videos",
            "duration_sec": 20.0,
            "source_exists": True,
        },
        "provenance": {
            "understanding_profile_id": "vision_baseline_v1",
            "understanding_mode": "tags",
            "components": {},
            "chunk_source": {},
            "keyframe_strategy": "midpoint",
            "generated_at": "2026-09-07T00:00:00Z",
        },
        "chunks": [
            {
                "chunk_index": 0,
                "start_sec": 0.0,
                "end_sec": 5.0,
                "sample": {"timestamp_sec": 2.5, "strategy": "midpoint"},
                "evidence": {"vision": {}, "audio": {}},
                "tags": list(tags0 if tags0 is not None else ["person", "table"]),
            },
            {
                "chunk_index": 1,
                "start_sec": 5.0,
                "end_sec": 10.0,
                "sample": {"timestamp_sec": 7.5, "strategy": "midpoint"},
                "evidence": {"vision": {}, "audio": {}},
                "tags": list(tags1 if tags1 is not None else ["car"]),
            },
        ],
    }


class EvidenceTagsStoreTests(unittest.TestCase):
    def test_replace_search_delete_and_incremental(self):
        from src.storage import evidence_tags_store as store

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                store._SCHEMA_READY.clear()
                n = store.replace_video_tags_from_bundle("vid1", _sample_bundle())
                self.assertEqual(n, 3)
                stats = store.get_tag_index_stats()
                self.assertTrue(stats["tag_index_ready"])
                self.assertEqual(stats["tag_indexed_videos"], 1)
                self.assertEqual(stats["tag_rows"], 3)

                hits = store.search_tags("person", match_mode="exact", top_k=5)
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["chunk_index"], 0)
                self.assertIn("person", hits[0]["matched_tags"])
                # Display uses the full chunk tag set, not only the hit tags.
                self.assertEqual(hits[0]["chunk_tags"], ["person", "table"])

                suggestions = store.suggest_tags("per", limit=10)
                self.assertIn("person", suggestions)

                popular = store.suggest_tags("", limit=10)
                self.assertTrue(len(popular) >= 1)

                # Cache: second popular call should hit without error and match.
                popular2 = store.suggest_tags("", limit=10)
                self.assertEqual(popular, popular2)
                self.assertGreaterEqual(len(store._SUGGEST_CACHE), 1)

                cooccur = store.suggest_tags(
                    "",
                    limit=10,
                    required_tags=["person"],
                    exclude_tags=["person"],
                )
                self.assertIn("table", cooccur)
                self.assertNotIn("person", cooccur)

                and_hits = store.search_tags(
                    "",
                    required_tags=["person", "table"],
                    match_mode="exact",
                    top_k=5,
                )
                self.assertEqual(len(and_hits), 1)
                self.assertEqual(and_hits[0]["chunk_index"], 0)

                and_miss = store.search_tags(
                    "",
                    required_tags=["person", "road"],
                    match_mode="exact",
                    top_k=5,
                )
                self.assertEqual(len(and_miss), 0)

                # Prose / slash noise must not enter the projection.
                n3 = store.replace_video_tags_from_bundle(
                    "vid1",
                    _sample_bundle(
                        tags0=[
                            "人物/动作/场景",
                            "佩戴长手套的女性角色正伸手触碰一张橙色皮质座椅",
                            "镜头聚焦于其上半身和手臂动作。",
                        ],
                        tags1=[],
                    ),
                )
                self.assertEqual(n3, 3)
                projected = store.suggest_tags("", limit=20)
                self.assertEqual(set(projected), {"人物", "动作", "场景"})

                # Checkpoint-style replace with extra chunk tags.
                n2 = store.replace_video_tags_from_bundle(
                    "vid1",
                    _sample_bundle(tags0=["person", "chair"], tags1=["car", "road"]),
                )
                self.assertEqual(n2, 4)
                stats2 = store.get_tag_index_stats()
                self.assertEqual(stats2["tag_rows"], 4)

                deleted = store.delete_video_tags("vid1")
                self.assertGreater(deleted, 0)
                self.assertFalse(store.get_tag_index_stats()["tag_index_ready"])

    def test_rebuild_all_from_json(self):
        from src.storage import evidence_tags_store as store

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            tags_dir = os.path.join(data_dir, "evidence", "tags")
            os.makedirs(tags_dir, exist_ok=True)
            bundle = _sample_bundle()
            with open(os.path.join(tags_dir, "vid1.json"), "w", encoding="utf-8") as fh:
                json.dump(bundle, fh, ensure_ascii=False)

            cfg = {"data_root": tmp}
            with (
                mock.patch(
                    "src.storage.dialogue_transcript_store.get_data_storage_paths",
                    return_value={"data_dir": data_dir},
                ),
                mock.patch(
                    "src.services.understanding_paths.get_data_storage_paths",
                    return_value={"data_dir": data_dir},
                ),
            ):
                store._SCHEMA_READY.clear()
                result = store.rebuild_all_from_json(config=cfg)
                self.assertTrue(result["ok"])
                self.assertEqual(result["videos_projected"], 1)
                self.assertEqual(result["tag_rows"], 3)
                hits = store.search_tags("table", match_mode="exact")
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["video_id"], "vid1")

                entries = store.list_tag_search_scope_entries()
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0]["video_id"], "vid1")
                self.assertEqual(entries[0]["asset_state"], "ready")

    def test_rebuild_all_from_motion_json(self):
        from src.storage import evidence_tags_store as store

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            motion_dir = os.path.join(data_dir, "evidence", "motion")
            os.makedirs(motion_dir, exist_ok=True)
            bundle = _sample_bundle()
            bundle["provenance"]["understanding_mode"] = "motion"
            with open(os.path.join(motion_dir, "vid_motion.json"), "w", encoding="utf-8") as fh:
                json.dump(bundle, fh, ensure_ascii=False)

            cfg = {"data_root": tmp}
            with (
                mock.patch(
                    "src.storage.dialogue_transcript_store.get_data_storage_paths",
                    return_value={"data_dir": data_dir},
                ),
                mock.patch(
                    "src.services.understanding_paths.get_data_storage_paths",
                    return_value={"data_dir": data_dir},
                ),
            ):
                store._SCHEMA_READY.clear()
                result = store.rebuild_all_from_json(config=cfg)
                self.assertTrue(result["ok"])
                self.assertEqual(result["videos_projected"], 1)
                self.assertEqual(result.get("scanned_by_store", {}).get("motion"), 1)
                self.assertEqual(result["tag_rows"], 3)
                hits = store.search_tags("person", match_mode="exact")
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["video_id"], "vid_motion")


class RunTagSearchTests(unittest.TestCase):
    def test_run_tag_search_exact(self):
        from src.services.search_service import run_tag_search
        from src.storage import evidence_tags_store as store

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                store._SCHEMA_READY.clear()
                store.replace_video_tags_from_bundle("vid1", _sample_bundle())
                hits, message, matched_by = run_tag_search(
                    "person",
                    top_k=5,
                    match_mode="exact",
                    config={"data_root": tmp},
                )
                self.assertEqual(message, "")
                self.assertEqual(matched_by, "keyword")
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0].match_kind, "tags")
                self.assertIn("person", hits[0].matched_text)
                self.assertIn("table", hits[0].matched_text)
                self.assertEqual(hits[0].start_sec, 0.0)
                self.assertEqual(hits[0].end_sec, 5.0)


    def test_run_tag_search_and_terms(self):
        from src.services.search_service import run_tag_search
        from src.storage import evidence_tags_store as store

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                store._SCHEMA_READY.clear()
                store.replace_video_tags_from_bundle("vid1", _sample_bundle())
                hits, message, matched_by = run_tag_search(
                    "person · table",
                    top_k=5,
                    match_mode="exact",
                    config={"data_root": tmp},
                )
                self.assertEqual(message, "")
                self.assertEqual(matched_by, "keyword")
                self.assertEqual(len(hits), 1)
                hits2, message2, _ = run_tag_search(
                    "",
                    required_tags=["person", "table"],
                    top_k=5,
                    match_mode="exact",
                    config={"data_root": tmp},
                )
                self.assertEqual(message2, "")
                self.assertEqual(len(hits2), 1)


class AgentTagSearchTests(unittest.TestCase):
    @mock.patch("src.web.agent_api.search.run_tag_search")
    @mock.patch("src.storage.evidence_tags_store.get_tag_index_stats")
    @mock.patch("src.web.agent_api.search._resolve_agent_search_scope")
    def test_execute_tag_search(self, mock_scope, mock_stats, mock_run):
        from src.domain.search_hit import SearchHit
        from src.web.agent_api.schemas import AgentSearchRequest
        from src.web.agent_api.search import execute_agent_search

        mock_scope.return_value = (None, None)
        mock_stats.return_value = {
            "tag_index_ready": True,
            "tag_indexed_videos": 1,
            "tag_rows": 3,
        }
        mock_run.return_value = (
            [
                SearchHit(
                    0.0,
                    5.0,
                    1.0,
                    "D:/Videos/ep01.mp4",
                    match_kind="tags",
                    video_id="vid1",
                    matched_text="person · table",
                )
            ],
            "",
            "keyword",
        )
        body = AgentSearchRequest(query="person", search_kind="tags", top_k=3)
        payload = execute_agent_search(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["search_kind"], "tags")
        self.assertEqual(payload["hits"][0]["matched_text"], "person · table")
        self.assertEqual(payload["hits"][0]["match_kind"], "tags")

    @mock.patch("src.storage.evidence_tags_store.get_tag_index_stats")
    @mock.patch("src.services.indexing_runtime_status.get_index_sync_status", return_value={})
    @mock.patch("src.web.agent_api.health._index_snapshot")
    @mock.patch("src.web.agent_api.health.get_active_embedding_spec")
    @mock.patch("src.web.agent_api.health.load_config", return_value={})
    @mock.patch("src.storage.lance_dialogue_search.get_dialogue_index_stats")
    def test_health_includes_tag_fields(
        self,
        mock_dialogue,
        _cfg,
        mock_spec,
        mock_snapshot,
        _sync,
        mock_tags,
    ):
        from src.web.agent_api.health import build_health_payload

        mock_dialogue.return_value = {
            "dialogue_index_ready": False,
            "dialogue_indexed_videos": 0,
            "dialogue_rows": 0,
        }
        mock_tags.return_value = {
            "tag_index_ready": True,
            "tag_indexed_videos": 2,
            "tag_rows": 10,
        }
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
            "chunk_vector_count": 0,
            "search_index_schema_version": 1,
            "library_indexes_upgrade_needed": False,
            "library_index_count": 1,
            "library_indexes_ready": 1,
            "library_indexes_stale": 0,
            "frame_index_ready": True,
            "chunk_index_ready": False,
        }
        payload = build_health_payload()
        self.assertTrue(payload["tag_index_ready"])
        self.assertEqual(payload["tag_indexed_videos"], 2)
        self.assertTrue(payload["capabilities"]["tag_search"])


if __name__ == "__main__":
    unittest.main()
