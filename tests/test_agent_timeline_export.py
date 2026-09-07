"""Tests for Agent API multi-clip timeline export."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from src.web.agent_api.schemas import AgentTimelineClipItem, AgentTimelineExportRequest
from src.web.agent_api.timeline_export import (
    execute_agent_timeline_export,
    normalize_timeline_items,
    _normalize_format,
)


class TimelineNormalizeTests(unittest.TestCase):
    def test_point_and_range_items(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            path = handle.name
            handle.write(b"fake")
        try:
            items = [
                AgentTimelineClipItem(
                    video_path=path,
                    time_sec=12.0,
                    client_request_id="a",
                ),
                AgentTimelineClipItem(
                    video_path=path,
                    start_sec=1.0,
                    end_sec=4.5,
                    client_request_id="b",
                ),
            ]
            shots, skipped = normalize_timeline_items(items)
            self.assertEqual(skipped, [])
            self.assertEqual(len(shots), 2)
            self.assertEqual(shots[0].match_kind, "frame")
            self.assertEqual(shots[0].start_sec, 12.0)
            self.assertEqual(shots[0].end_sec, 12.0)
            self.assertEqual(shots[1].match_kind, "segment")
            self.assertEqual(shots[1].start_sec, 1.0)
            self.assertEqual(shots[1].end_sec, 4.5)
        finally:
            os.unlink(path)

    def test_missing_path_skipped(self):
        items = [
            AgentTimelineClipItem(video_path="D:/no_such_clip_xyz.mp4", time_sec=1.0),
        ]
        shots, skipped = normalize_timeline_items(items)
        self.assertEqual(shots, [])
        self.assertEqual(skipped[0]["reason"], "missing")

    def test_empty_items_raises(self):
        with self.assertRaises(ValueError):
            normalize_timeline_items([])

    def test_format_aliases(self):
        self.assertEqual(_normalize_format("resolve"), "fcpxml")
        self.assertEqual(_normalize_format("premiere"), "fcp7_xml")
        self.assertEqual(_normalize_format("jianying"), "jianying")
        with self.assertRaises(ValueError):
            _normalize_format("edl")


class TimelineExecuteTests(unittest.TestCase):
    def test_empty_items_400(self):
        body = AgentTimelineExportRequest(format="fcpxml", items=[], write_path="D:/out.fcpxml")
        with self.assertRaises(ValueError):
            execute_agent_timeline_export(body)

    def test_invalid_format(self):
        body = AgentTimelineExportRequest(
            format="edl",
            items=[AgentTimelineClipItem(video_path="D:/a.mp4", time_sec=1.0)],
        )
        with self.assertRaises(ValueError):
            execute_agent_timeline_export(body)

    @patch("src.web.agent_api.timeline_export.os.path.isfile", return_value=True)
    @patch("src.services.fcpxml_export_service.export_shot_list_nle_xml")
    @patch("src.services.agent_clip_service._output_path_allowed", return_value=True)
    def test_fcpxml_dispatch(self, _allowed, mock_export, _isfile):
        mock_export.return_value = {
            "ok": True,
            "write_path": "D:/Exports/out.fcpxml",
            "format": "fcpxml",
            "clip_count": 1,
            "exported_count": 1,
            "skipped_remote": 0,
            "skipped_missing": 0,
            "fcpxml_version": "1.9",
        }
        body = AgentTimelineExportRequest(
            format="fcpxml",
            write_path="D:/Exports/out",
            items=[
                AgentTimelineClipItem(video_path="D:/lib/a.mp4", time_sec=10.0),
                AgentTimelineClipItem(video_path="D:/lib/b.mp4", start_sec=1.0, end_sec=3.0),
            ],
        )
        payload = execute_agent_timeline_export(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["format"], "fcpxml")
        self.assertEqual(payload["clip_count"], 1)
        self.assertEqual(payload["export_path"], "D:/Exports/out.fcpxml")
        mock_export.assert_called_once()
        write_path = mock_export.call_args.kwargs["write_path"]
        self.assertTrue(str(write_path).lower().endswith(".fcpxml"))
        shots = mock_export.call_args.args[0]
        self.assertEqual(len(shots), 2)
        self.assertEqual(shots[0].match_kind, "frame")
        self.assertEqual(shots[1].match_kind, "segment")

    @patch("src.web.agent_api.timeline_export.os.path.isfile", return_value=True)
    @patch("src.services.fcpxml_export_service.export_shot_list_nle_xml")
    @patch("src.services.agent_clip_service._output_path_allowed", return_value=True)
    def test_fcpxml_output_dir_auto_name(self, _allowed, mock_export, _isfile):
        mock_export.return_value = {
            "ok": True,
            "write_path": "D:/Exports/RoughCut.fcpxml",
            "format": "fcpxml",
            "clip_count": 1,
            "exported_count": 1,
            "skipped_remote": 0,
            "skipped_missing": 0,
        }
        body = AgentTimelineExportRequest(
            format="fcpxml",
            project="RoughCut",
            output_dir="D:/Exports",
            items=[AgentTimelineClipItem(video_path="D:/lib/a.mp4", time_sec=2.0)],
        )
        payload = execute_agent_timeline_export(body)
        write_path = mock_export.call_args.kwargs["write_path"]
        self.assertTrue(str(write_path).replace("\\", "/").endswith("/RoughCut.fcpxml"))
        self.assertEqual(payload["export_path"], "D:/Exports/RoughCut.fcpxml")

    def test_xml_requires_path(self):
        body = AgentTimelineExportRequest(
            format="fcp7_xml",
            items=[AgentTimelineClipItem(video_path="D:/lib/a.mp4", time_sec=1.0)],
        )
        with patch("src.web.agent_api.timeline_export.os.path.isfile", return_value=True):
            with self.assertRaises(ValueError) as ctx:
                execute_agent_timeline_export(body)
        self.assertIn("output_dir", str(ctx.exception))

    @patch("src.web.agent_api.timeline_export.os.path.isfile", return_value=True)
    @patch(
        "src.services.jianying_draft_service.export_shot_list_to_jianying_draft",
    )
    @patch(
        "src.services.jianying_draft_service.is_jianying_draft_support_available",
        return_value=True,
    )
    def test_jianying_dispatch(self, _avail, mock_export, _isfile):
        mock_export.return_value = {
            "draft_name": "VideoSeek导入-1",
            "drafts_dir": "D:/Drafts",
            "draft_path": "D:/Drafts/VideoSeek导入-1",
            "exported_count": 1,
            "skipped_count": 0,
            "skipped": [],
        }
        body = AgentTimelineExportRequest(
            format="jianying",
            drafts_dir="D:/Drafts",
            items=[AgentTimelineClipItem(video_path="D:/lib/a.mp4", time_sec=5.0)],
        )
        payload = execute_agent_timeline_export(body)
        self.assertEqual(payload["format"], "jianying")
        self.assertEqual(payload["draft_name"], "VideoSeek导入-1")
        self.assertEqual(payload["clip_count"], 1)
        self.assertEqual(payload["export_path"], "D:/Drafts/VideoSeek导入-1")
        mock_export.assert_called_once()


class TimelineHealthTests(unittest.TestCase):
    @patch("src.web.agent_api.health.get_search_scope_mode", return_value="all")
    @patch("src.web.agent_api.health._build_ffmpeg_info")
    @patch("src.web.agent_api.health._index_snapshot")
    @patch("src.web.agent_api.health.get_active_embedding_spec")
    @patch("src.services.library_service.list_libraries", return_value={})
    @patch("src.web.agent_api.health.get_search_mode", return_value="frame")
    @patch("src.web.agent_api.health._jianying_draft_available", return_value=True)
    def test_health_timeline_caps(
        self, _jy, _mode, _libs, mock_spec, mock_snapshot, mock_ffmpeg, _scope
    ):
        from src.web.agent_api.health import build_health_payload

        mock_spec.return_value = {
            "model_id": "clip",
            "provider": "clip",
            "embedding_space": "clip",
            "dimension": 512,
            "metric": "ip",
        }
        mock_snapshot.return_value = {
            "index_ready": True,
            "index_stale": False,
            "global_index_state": "fresh",
            "vector_count": 1,
            "indexed_video_paths": 1,
            "frame_index_ready": True,
            "chunk_index_ready": False,
            "frame_vector_count": 1,
            "chunk_vector_count": 0,
            "search_index_schema_version": 1,
            "library_indexes_upgrade_needed": False,
            "library_index_count": 0,
            "library_indexes_ready": 0,
            "library_indexes_stale": 0,
        }
        mock_ffmpeg.return_value = {
            "ffmpeg_available": True,
            "ffmpeg_path": "ffmpeg",
            "ffmpeg_source": "managed",
        }
        payload = build_health_payload()
        caps = payload["capabilities"]
        self.assertTrue(caps["timeline_export"])
        self.assertTrue(caps["nle_xml_export"])
        self.assertTrue(caps["jianying_draft"])


if __name__ == "__main__":
    unittest.main()
