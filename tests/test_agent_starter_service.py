import os
import tempfile
import unittest
from unittest.mock import patch

from src.services.agent_starter_service import (
    AGENT_DOC_REL,
    agent_doc_rel_path,
    build_agent_doc_payload,
    build_agent_starter_payload,
    build_agent_starter_text,
    read_agent_doc_content,
    resolve_full_agent_doc_path,
    _format_doc_reference,
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
    def test_starter_text_uses_absolute_doc_path_when_available(self, mock_get_resource_path):
        doc_path = os.path.normpath("D:/Release/VideoSeek/docs/for-agents.md")
        mock_get_resource_path.return_value = doc_path
        with patch("src.services.agent_starter_service.os.path.isfile", return_value=True):
            text = build_agent_starter_text(
                "http://127.0.0.1:8765",
                self._sample_health(),
                locale="zh",
            )
        self.assertLess(len(text.splitlines()), 80)
        self.assertIn("GET http://127.0.0.1:8765/api/v1/libraries", text)
        self.assertIn("export/clips/batch", text)
        self.assertIn("chinese_clip_vit_base_patch16", text)
        self.assertIn("Release\\\\VideoSeek\\\\docs\\\\for-agents.md", text)
        self.assertIn("/agent-doc?format=text", text)
        self.assertIn('"full_doc_path"', text)
        self.assertIn('"capabilities"', text)
        self.assertNotIn("capabilities:\n- enabled", text)

    @patch("src.services.agent_starter_service.get_resource_path")
    def test_starter_text_missing_doc_still_points_to_agent_doc(self, mock_get_resource_path):
        mock_get_resource_path.return_value = "D:/Release/VideoSeek/docs/for-agents.md"
        with patch("src.services.agent_starter_service.os.path.isfile", return_value=False):
            text = build_agent_starter_text(
                "http://127.0.0.1:8765",
                self._sample_health(),
                locale="en",
            )
        self.assertIn("/agent-doc?format=text", text)
        self.assertIn("do not scan the disk", text)
        self.assertIn('"full_doc_path": null', text)

    def test_format_doc_reference_en(self):
        line = _format_doc_reference(
            locale="en",
            api_base="http://127.0.0.1:8765/api/v1",
        )
        self.assertIn("/agent-doc?format=text", line)
        self.assertIn("do not scan the disk", line)

    @patch("src.services.agent_starter_service.get_resource_path")
    def test_build_agent_doc_payload(self, mock_get_resource_path):
        with tempfile.TemporaryDirectory() as tmp:
            doc_path = os.path.join(tmp, "docs", "for-agents.md")
            os.makedirs(os.path.dirname(doc_path), exist_ok=True)
            with open(doc_path, "w", encoding="utf-8") as handle:
                handle.write("# Agent doc\n\n## API\n")
            mock_get_resource_path.return_value = doc_path

            payload = build_agent_doc_payload(api_version="1")
            self.assertTrue(payload["ok"])
            self.assertIn("# Agent doc", payload["content"])
            self.assertEqual(payload["full_doc_rel"], "docs/for-agents.md")
            self.assertEqual(payload["full_doc_path"], os.path.normpath(doc_path))
            self.assertEqual(payload["meta"]["line_count"], 4)
            self.assertEqual(read_agent_doc_content(), payload["content"])

    @patch("src.services.agent_starter_service.get_resource_path")
    def test_build_agent_doc_payload_missing(self, mock_get_resource_path):
        mock_get_resource_path.return_value = "D:/missing/docs/for-agents.md"
        with patch("src.services.agent_starter_service.os.path.isfile", return_value=False):
            with self.assertRaises(FileNotFoundError):
                build_agent_doc_payload()

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
            self.assertIn("Workflow", payload["starter_text"])
            self.assertIn("/agent-doc?format=text", payload["starter_text"])
            self.assertIn("do not scan the disk", payload["starter_text"])
            self.assertLessEqual(payload["meta"]["line_count"], 80)


if __name__ == "__main__":
    unittest.main()
