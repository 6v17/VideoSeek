import unittest
from unittest.mock import patch

from src.services.agent_evidence_service import (
    AgentEvidenceError,
    filter_evidence_bundle_by_time_window,
    get_agent_video_evidence,
    resolve_agent_video_id,
)


SAMPLE_BUNDLE = {
    "schema_version": 1,
    "video": {"video_id": "vid123", "video_path": "D:/Videos/demo.mp4"},
    "provenance": {
        "understanding_profile_id": "vision_baseline_v1",
        "components": {},
        "generation_status": "completed",
        "chunk_total": 2,
        "chunks_completed": 2,
    },
    "chunks": [
        {
            "chunk_index": 0,
            "start_sec": 0.0,
            "end_sec": 4.0,
            "sample": {"timestamp_sec": 2.0, "strategy": "midpoint"},
            "evidence": {"vision": {}, "audio": {}},
        },
        {
            "chunk_index": 1,
            "start_sec": 4.0,
            "end_sec": 8.0,
            "sample": {"timestamp_sec": 6.0, "strategy": "midpoint"},
            "evidence": {"vision": {}, "audio": {}},
        },
    ],
    "summary": {"text": "demo summary", "source": "vision/image_caption/qwen3-vl-remote"},
}


class AgentEvidenceServiceTests(unittest.TestCase):
    def test_filter_evidence_bundle_by_time_window(self):
        filtered = filter_evidence_bundle_by_time_window(
            SAMPLE_BUNDLE,
            start_sec=3.0,
            end_sec=5.0,
        )
        self.assertEqual(len(filtered["chunks"]), 2)

        filtered = filter_evidence_bundle_by_time_window(
            SAMPLE_BUNDLE,
            start_sec=5.0,
            end_sec=6.0,
        )
        self.assertEqual(len(filtered["chunks"]), 1)
        self.assertEqual(filtered["chunks"][0]["chunk_index"], 1)

    @patch("src.services.agent_evidence_service._resolve_video_id_for_path", return_value="vid123")
    def test_resolve_agent_video_id_from_path(self, _mock_resolve):
        video_id = resolve_agent_video_id(video_path="D:/Videos/demo.mp4", config={})
        self.assertEqual(video_id, "vid123")

    @patch("src.services.agent_evidence_service.load_evidence_bundle", return_value=SAMPLE_BUNDLE)
    @patch("src.services.agent_evidence_service.resolve_video_context")
    @patch("src.services.agent_evidence_service.resolve_agent_video_id", return_value="vid123")
    def test_get_agent_video_evidence_reads_existing_bundle(
        self,
        _mock_resolve_id,
        mock_context,
        _mock_load,
    ):
        mock_context.return_value = {"video_path": "D:/Videos/demo.mp4"}
        payload = get_agent_video_evidence(video_id="vid123", start_sec=0.0, end_sec=3.0, config={})
        self.assertTrue(payload["evidence_available"])
        self.assertEqual(payload["video_id"], "vid123")
        self.assertEqual(len(payload["chunks"]), 1)
        self.assertEqual(payload["summary"]["text"], "demo summary")

    @patch("src.services.agent_evidence_service.load_evidence_bundle", return_value=None)
    @patch("src.services.agent_evidence_service.resolve_video_context")
    @patch("src.services.agent_evidence_service.resolve_agent_video_id", return_value="vid123")
    def test_get_agent_video_evidence_missing_without_ensure(
        self,
        _mock_resolve_id,
        mock_context,
        _mock_load,
    ):
        mock_context.return_value = {"video_path": "D:/Videos/demo.mp4"}
        payload = get_agent_video_evidence(video_id="vid123", ensure=False, config={})
        self.assertFalse(payload["evidence_available"])
        self.assertEqual(payload["chunks"], [])

    @patch("src.services.agent_evidence_service.load_evidence_bundle")
    @patch("src.services.agent_evidence_service.generate_evidence_for_video")
    @patch(
        "src.services.agent_evidence_service.get_understanding_resource_status",
        return_value={"understanding_ready": True, "missing_components": []},
    )
    @patch("src.services.agent_evidence_service.resolve_video_context")
    @patch("src.services.agent_evidence_service.resolve_agent_video_id", return_value="vid123")
    def test_get_agent_video_evidence_generates_when_ensure_true(
        self,
        _mock_resolve_id,
        mock_context,
        _mock_status,
        mock_generate,
        mock_load,
    ):
        mock_context.return_value = {"video_path": "D:/Videos/demo.mp4"}
        mock_load.side_effect = [None, SAMPLE_BUNDLE]
        mock_generate.return_value = {
            "video_id": "vid123",
            "evidence_path": "D:/data/evidence/videos/vid123.json",
            "chunk_count": 2,
            "chunk_total": 2,
        }
        payload = get_agent_video_evidence(video_id="vid123", ensure=True, config={})
        self.assertTrue(payload["evidence_available"])
        self.assertEqual(len(payload["chunks"]), 2)
        self.assertEqual(payload["meta"]["generated_by"], "agent_api")
        self.assertEqual(payload["meta"]["chunk_count"], 2)
        self.assertEqual(payload["meta"]["generation_status"], "completed")
        mock_generate.assert_called_once()
        self.assertEqual(mock_generate.call_args.args[0], "vid123")
        mock_load.assert_called()

    @patch("src.services.agent_evidence_service.load_evidence_bundle")
    @patch("src.services.agent_evidence_service.generate_evidence_for_video")
    @patch(
        "src.services.agent_evidence_service.get_understanding_resource_status",
        return_value={"understanding_ready": True, "missing_components": []},
    )
    @patch("src.services.agent_evidence_service.resolve_video_context")
    @patch("src.services.agent_evidence_service.resolve_agent_video_id", return_value="vid123")
    def test_get_agent_video_evidence_resumes_in_progress_when_ensure_true(
        self,
        _mock_resolve_id,
        mock_context,
        _mock_status,
        mock_generate,
        mock_load,
    ):
        partial_bundle = {
            **SAMPLE_BUNDLE,
            "provenance": {
                **SAMPLE_BUNDLE["provenance"],
                "generation_status": "in_progress",
                "chunk_total": 2,
                "chunks_completed": 1,
            },
            "chunks": SAMPLE_BUNDLE["chunks"][:1],
        }
        completed_bundle = SAMPLE_BUNDLE
        mock_context.return_value = {"video_path": "D:/Videos/demo.mp4"}
        mock_load.side_effect = [partial_bundle, completed_bundle]
        payload = get_agent_video_evidence(video_id="vid123", ensure=True, config={})
        self.assertTrue(payload["evidence_available"])
        self.assertEqual(payload["meta"]["generation_status"], "completed")
        mock_generate.assert_called_once()

    @patch("src.services.agent_evidence_service.load_evidence_bundle")
    @patch("src.services.agent_evidence_service.resolve_video_context")
    @patch("src.services.agent_evidence_service.resolve_agent_video_id", return_value="vid123")
    def test_get_agent_video_evidence_returns_partial_without_ensure(
        self,
        _mock_resolve_id,
        mock_context,
        mock_load,
    ):
        partial_bundle = {
            **SAMPLE_BUNDLE,
            "provenance": {
                **SAMPLE_BUNDLE["provenance"],
                "generation_status": "in_progress",
                "chunk_total": 4,
                "chunks_completed": 1,
            },
            "chunks": SAMPLE_BUNDLE["chunks"][:1],
        }
        mock_context.return_value = {"video_path": "D:/Videos/demo.mp4"}
        mock_load.return_value = partial_bundle
        payload = get_agent_video_evidence(video_id="vid123", ensure=False, config={})
        self.assertTrue(payload["evidence_available"])
        self.assertEqual(payload["meta"]["generation_status"], "in_progress")
        self.assertEqual(payload["meta"]["chunks_completed"], 1)
        self.assertEqual(payload["meta"]["chunk_total"], 4)

    @patch(
        "src.services.agent_evidence_service.get_understanding_resource_status",
        return_value={"understanding_ready": False, "missing_components": ["vision/image_caption/qwen3-vl-remote"]},
    )
    @patch("src.services.agent_evidence_service.load_evidence_bundle", return_value=None)
    @patch("src.services.agent_evidence_service.resolve_video_context")
    @patch("src.services.agent_evidence_service.resolve_agent_video_id", return_value="vid123")
    def test_get_agent_video_evidence_not_ready_raises(
        self,
        _mock_resolve_id,
        mock_context,
        _mock_load,
        _mock_status,
    ):
        mock_context.return_value = {"video_path": "D:/Videos/demo.mp4"}
        with self.assertRaises(AgentEvidenceError) as ctx:
            get_agent_video_evidence(video_id="vid123", ensure=True, config={})
        self.assertEqual(ctx.exception.code, "understanding_not_ready")
        self.assertEqual(ctx.exception.status_code, 409)

    @patch("src.services.agent_evidence_service.load_evidence_bundle")
    def test_list_agent_evidence_status(self, mock_load):
        from src.services.agent_evidence_service import list_agent_evidence_status

        def side_effect(video_id, **kwargs):
            if video_id == "a":
                return {
                    "provenance": {"generation_status": "completed", "chunk_total": 2, "chunks_completed": 2},
                    "chunks": [{}, {}],
                }
            if video_id == "b":
                return {
                    "provenance": {"generation_status": "in_progress", "chunk_total": 4, "chunks_completed": 1},
                    "chunks": [{}],
                }
            return None

        mock_load.side_effect = side_effect
        payload = list_agent_evidence_status(["a", "b", "c"], config={})
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["items"][0]["has_evidence"])
        self.assertEqual(payload["items"][0]["generation_status"], "completed")
        self.assertTrue(payload["items"][1]["has_evidence"])
        self.assertEqual(payload["items"][1]["generation_status"], "in_progress")
        self.assertFalse(payload["items"][2]["has_evidence"])

    def test_list_agent_evidence_status_requires_ids(self):
        from src.services.agent_evidence_service import list_agent_evidence_status

        with self.assertRaises(ValueError):
            list_agent_evidence_status([])


if __name__ == "__main__":
    unittest.main()
