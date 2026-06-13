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
    _search_preset_summaries,
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
    @patch("src.services.agent_starter_service._search_preset_summaries")
    def test_starter_text_uses_absolute_doc_path_when_available(
        self, mock_presets, mock_get_resource_path
    ):
        mock_presets.return_value = [
            {
                "id": "builtin_smile",
                "name": "开心",
                "query": "a person with a big smile",
                "summary": "a person with a big smile",
            },
        ]
        doc_path = os.path.normpath("D:/Release/VideoSeek/docs/for-agents.md")
        mock_get_resource_path.return_value = doc_path
        with patch("src.services.agent_starter_service.os.path.isfile", return_value=True):
            text = build_agent_starter_text(
                "http://127.0.0.1:8765",
                self._sample_health(),
                locale="zh",
            )
        self.assertLess(len(text.splitlines()), 145)
        self.assertIn("GET http://127.0.0.1:8765/api/v1/libraries", text)
        self.assertIn("search_presets", text)
        self.assertIn("builtin_smile", text)
        self.assertIn("curl.exe", text)
        self.assertIn("top_k", text)
        self.assertIn("Policy kernel", text)
        self.assertIn("non-binding", text)
        self.assertIn("ONLY starter", text)
        self.assertIn("image_folder", text)
        self.assertIn("export.output_dir", text)
        self.assertIn("search→manifest→clips", text)
        self.assertIn("chinese_clip_vit_base_patch16", text)
        self.assertIn("agent_api_default_image_precision", text)
        self.assertNotIn("图搜 precise", text)
        self.assertNotIn("## 流程", text)
        self.assertNotIn("黄金路径", text)
        self.assertIn("Release\\\\VideoSeek\\\\docs\\\\for-agents.md", text)
        self.assertIn("/agent-doc?format=text", text)
        self.assertIn('"full_doc_path"', text)
        self.assertIn('"capabilities"', text)
        self.assertNotIn("capabilities:\n- enabled", text)

    @patch("src.web.agent_api.list_agent_search_presets")
    def test_search_preset_summaries_from_agent_api(self, mock_list):
        mock_list.return_value = {
            "ok": True,
            "presets": [
                {"id": "builtin_smile", "name": "开心", "query": "a person with a big smile", "summary": "a person with a big smile"},
                {"id": "custom_broll", "name": "B-roll", "query": "产品特写 桌面", "summary": "产品特写 桌面", "reference_image_count": 2},
            ],
        }
        summaries = _search_preset_summaries(limit=10)
        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]["id"], "builtin_smile")
        self.assertEqual(summaries[0]["query"], "a person with a big smile")
        self.assertEqual(summaries[1]["query"], "产品特写 桌面")
        self.assertEqual(summaries[1]["reference_image_count"], 2)

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
    @patch("src.services.agent_starter_service._search_preset_summaries", return_value=[])
    def test_starter_payload_shape(self, _mock_presets, mock_get_resource_path):
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
            self.assertIn("Policy kernel", payload["starter_text"])
            self.assertIn("non-binding", payload["starter_text"])
            self.assertNotIn("Workflow", payload["starter_text"])
            self.assertIn("preset", payload["starter_text"].lower())
            self.assertIn("/agent-doc?format=text", payload["starter_text"])
            self.assertIn("do not scan the disk", payload["starter_text"])
            self.assertEqual(payload["meta"]["search_preset_count"], 0)
            self.assertLessEqual(payload["meta"]["line_count"], 145)


class ForAgentsDocTests(unittest.TestCase):
    def test_for_agents_doc_is_capability_reference_only(self):
        doc_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "docs", "for-agents.md")
        )
        with open(doc_path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("agent-starter", content)
        self.assertIn("non-binding", content)
        self.assertIn("Policy kernel", content)
        self.assertNotIn("## ⭐ 默认路径", content)
        self.assertNotIn("## 5. 推荐工作流", content)
        self.assertNotIn("勿拆 search", content)
        self.assertNotIn("图搜 precise", content)


if __name__ == "__main__":
    unittest.main()
