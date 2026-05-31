import os
import tempfile
import unittest
from unittest.mock import patch

from src.services.agent_starter_service import (
    AGENT_DOC_REL,
    agent_doc_rel_path,
    build_agent_starter_payload,
    build_agent_starter_text,
    resolve_full_agent_doc_path,
)


class AgentStarterServiceTests(unittest.TestCase):
    def _sample_health(self):
        return {
            "api_version": "1",
            "index_ready": True,
            "index_stale": False,
            "model": "chinese_clip_vit_base_patch16",
            "provider": "chinese_clip_onnx",
            "search_mode_default": "frame",
            "video_count": 89,
            "vector_count": 1000,
            "saved_search_scope_mode": "all",
            "search_timeout_sec": 90,
            "search_timeout_precise_sec": 180,
            "agent_api_default_image_precision": "fast",
            "capabilities": {
                "export_clip": True,
                "library_discovery": True,
                "batch_search": True,
            },
            "ffmpeg": {
                "ffmpeg_available": True,
                "ffmpeg_path": "C:/ffmpeg/ffmpeg.exe",
            },
        }

    def test_agent_doc_rel_is_stable(self):
        self.assertEqual(agent_doc_rel_path(), "docs/for-agents.md")
        self.assertEqual(AGENT_DOC_REL, "docs/for-agents.md")

    @patch("src.services.agent_starter_service.get_resource_path")
    def test_resolve_full_agent_doc_path_uses_resource_path(self, mock_get_resource_path):
        with tempfile.TemporaryDirectory() as tmp:
            doc_path = os.path.join(tmp, "docs", "for-agents.md")
            os.makedirs(os.path.dirname(doc_path), exist_ok=True)
            with open(doc_path, "w", encoding="utf-8") as handle:
                handle.write("# test\n")
            mock_get_resource_path.return_value = doc_path
            resolved = resolve_full_agent_doc_path()
            mock_get_resource_path.assert_called_with("docs/for-agents.md")
            self.assertEqual(resolved, os.path.normpath(doc_path))

    @patch("src.services.agent_starter_service.get_resource_path")
    def test_starter_text_uses_relative_doc_path(self, mock_get_resource_path):
        mock_get_resource_path.return_value = "D:/Release/VideoSeek/docs/for-agents.md"
        text = build_agent_starter_text(
            "http://127.0.0.1:8765",
            self._sample_health(),
            locale="zh",
        )
        self.assertLess(len(text.splitlines()), 120)
        self.assertIn("GET http://127.0.0.1:8765/api/v1/health", text)
        self.assertIn("export/clip", text)
        self.assertIn("chinese_clip_vit_base_patch16", text)
        self.assertIn("完整 API 契约：docs/for-agents.md", text)
        self.assertNotIn("D:/Release/VideoSeek/docs/for-agents.md", text)

    @patch("src.services.agent_starter_service.get_resource_path")
    def test_starter_payload_shape(self, mock_get_resource_path):
        with tempfile.TemporaryDirectory() as tmp:
            doc_path = os.path.join(tmp, "docs", "for-agents.md")
            os.makedirs(os.path.dirname(doc_path), exist_ok=True)
            with open(doc_path, "w", encoding="utf-8") as handle:
                handle.write("# test\n")
            mock_get_resource_path.return_value = doc_path

            payload = build_agent_starter_payload(
                "http://127.0.0.1:8765",
                self._sample_health(),
                locale="en",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["full_doc_rel"], "docs/for-agents.md")
            self.assertEqual(payload["full_doc_path"], os.path.normpath(doc_path))
            self.assertTrue(payload["meta"]["doc_on_disk"])
            self.assertIn("starter_text", payload)
            self.assertIn("Minimal workflow", payload["starter_text"])
            self.assertIn("Full API contract: docs/for-agents.md", payload["starter_text"])
            self.assertLessEqual(payload["meta"]["line_count"], 120)


if __name__ == "__main__":
    unittest.main()
