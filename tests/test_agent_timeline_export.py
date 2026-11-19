"""Tests for Agent API multi-clip timeline export."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from src.services.manifest_export_service import dedupe_shots_by_start
from src.services.shot_list_service import ShotListItem
from src.web.agent_api.schemas import (
    AgentTimelineAudio,
    AgentTimelineClipItem,
    AgentTimelineExportRequest,
    AgentTimelinePlan,
    AgentTimelinePlanShot,
)
from src.web.agent_api.timeline_export import (
    execute_agent_timeline_export,
    normalize_timeline_items,
    _normalize_format,
)


class TimelineNormalizeTests(unittest.TestCase):
    def test_timeline_dedupes_by_path_and_start(self):
        shots = [
            ShotListItem("1", "D:/a.mp4", 10.0, 16.0, None, match_kind="chunk"),
            ShotListItem("2", "D:/a.mp4", 10.8, 18.0, None, match_kind="chunk"),
            ShotListItem("3", "D:/a.mp4", 10.0, 12.0, None, match_kind="chunk"),
            ShotListItem("4", "D:/b.mp4", 1.0, 2.0, None, match_kind="chunk"),
        ]
        kept, meta = dedupe_shots_by_start(shots, enabled=True)
        self.assertEqual([row.id for row in kept], ["1", "4"])
        self.assertEqual(meta, {"input": 4, "kept": 2, "dropped": 2, "dedupe": True})
        raw, raw_meta = dedupe_shots_by_start(shots, enabled=False)
        self.assertEqual(len(raw), 4)
        self.assertEqual(raw_meta["dropped"], 0)

    def test_timeline_accepts_a_long_cut(self):
        from src.web.agent_api.constants import MAX_TIMELINE_CLIPS

        self.assertGreaterEqual(MAX_TIMELINE_CLIPS, 200)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            path = handle.name
            handle.write(b"fake")
        try:
            items = [
                AgentTimelineClipItem(video_path=path, start_sec=float(i), end_sec=float(i) + 1.0)
                for i in range(187)
            ]
            shots, skipped = normalize_timeline_items(items)
            self.assertEqual(len(shots), 187)
            self.assertEqual(skipped, [])
            with self.assertRaises(ValueError) as ctx:
                normalize_timeline_items(
                    [
                        AgentTimelineClipItem(
                            video_path=path, start_sec=0.0, end_sec=1.0
                        )
                        for _ in range(MAX_TIMELINE_CLIPS + 1)
                    ]
                )
            self.assertIn(str(MAX_TIMELINE_CLIPS), str(ctx.exception))
        finally:
            os.unlink(path)

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
            AgentTimelineClipItem(video_path="no_such_clip_xyz.mp4", time_sec=1.0),
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
    def _video(self, directory: str, name: str) -> str:
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(b"fake")
        return path

    def test_empty_items_400(self):
        body = AgentTimelineExportRequest(format="fcpxml", items=[], write_path="out.fcpxml")
        with self.assertRaises(ValueError):
            execute_agent_timeline_export(body)

    def test_invalid_format(self):
        body = AgentTimelineExportRequest(
            format="edl",
            items=[AgentTimelineClipItem(video_path="a.mp4", time_sec=1.0)],
        )
        with self.assertRaises(ValueError):
            execute_agent_timeline_export(body)

    @patch("src.services.fcpxml_export_service.export_shot_list_nle_xml")
    @patch("src.services.clip_export_service.output_path_allowed", return_value=True)
    def test_fcpxml_dispatch(self, _allowed, mock_export):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.fcpxml")
            mock_export.return_value = {
                "ok": True,
                "write_path": out,
                "format": "fcpxml",
                "clip_count": 1,
                "exported_count": 1,
                "skipped_remote": 0,
                "skipped_missing": 0,
                "fcpxml_version": "1.9",
            }
            body = AgentTimelineExportRequest(
                format="fcpxml",
                write_path=os.path.join(tmp, "out"),
                items=[
                    AgentTimelineClipItem(video_path=self._video(tmp, "a.mp4"), time_sec=10.0),
                    AgentTimelineClipItem(
                        video_path=self._video(tmp, "b.mp4"),
                        start_sec=1.0,
                        end_sec=3.0,
                    ),
                ],
            )
            payload = execute_agent_timeline_export(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["format"], "fcpxml")
        self.assertEqual(payload["clip_count"], 1)
        self.assertEqual(payload["export_path"], out)
        mock_export.assert_called_once()
        write_path = mock_export.call_args.kwargs["write_path"]
        self.assertTrue(str(write_path).lower().endswith(".fcpxml"))
        shots = mock_export.call_args.args[0]
        self.assertEqual(len(shots), 2)
        self.assertEqual(shots[0].match_kind, "frame")
        self.assertEqual(shots[1].match_kind, "segment")

    @patch("src.services.fcpxml_export_service.export_shot_list_nle_xml")
    @patch("src.services.clip_export_service.output_path_allowed", return_value=True)
    def test_fcpxml_output_dir_auto_name(self, _allowed, mock_export):
        with tempfile.TemporaryDirectory() as tmp:
            exports = os.path.join(tmp, "Exports")
            expected = os.path.join(exports, "RoughCut.fcpxml")
            mock_export.return_value = {
                "ok": True,
                "write_path": expected,
                "format": "fcpxml",
                "clip_count": 1,
                "exported_count": 1,
                "skipped_remote": 0,
                "skipped_missing": 0,
            }
            body = AgentTimelineExportRequest(
                format="fcpxml",
                project="RoughCut",
                output_dir=exports,
                items=[AgentTimelineClipItem(video_path=self._video(tmp, "a.mp4"), time_sec=2.0)],
            )
            payload = execute_agent_timeline_export(body)
            write_path = mock_export.call_args.kwargs["write_path"]
        self.assertTrue(str(write_path).replace("\\", "/").endswith("/RoughCut.fcpxml"))
        self.assertEqual(payload["export_path"], expected)

    @patch("src.services.clip_export_service.output_path_allowed", return_value=True)
    def test_output_dir_not_writable(self, _allowed):
        with tempfile.TemporaryDirectory() as tmp:
            body = AgentTimelineExportRequest(
                format="fcpxml",
                output_dir=os.path.join(tmp, "missing-drive"),
                items=[AgentTimelineClipItem(video_path=self._video(tmp, "a.mp4"), time_sec=1.0)],
            )
            with patch(
                "src.web.agent_api.timeline_export.os.makedirs",
                side_effect=FileNotFoundError("missing drive"),
            ):
                with self.assertRaises(ValueError) as ctx:
                    execute_agent_timeline_export(body)
        self.assertIn("not writable", str(ctx.exception))

    def test_xml_requires_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = AgentTimelineExportRequest(
                format="fcp7_xml",
                items=[AgentTimelineClipItem(video_path=self._video(tmp, "a.mp4"), time_sec=1.0)],
            )
            with self.assertRaises(ValueError) as ctx:
                execute_agent_timeline_export(body)
        self.assertIn("output_dir", str(ctx.exception))

    @patch(
        "src.services.jianying_draft_service.export_shot_list_to_jianying_draft",
    )
    @patch(
        "src.services.jianying_draft_service.is_jianying_draft_support_available",
        return_value=True,
    )
    def test_jianying_dispatch(self, _avail, mock_export):
        with tempfile.TemporaryDirectory() as tmp:
            drafts = os.path.join(tmp, "Drafts")
            draft_path = os.path.join(drafts, "VideoSeek导入-1")
            mock_export.return_value = {
                "draft_name": "VideoSeek导入-1",
                "drafts_dir": drafts,
                "draft_path": draft_path,
                "exported_count": 1,
                "skipped_count": 0,
                "skipped": [],
            }
            body = AgentTimelineExportRequest(
                format="jianying",
                drafts_dir=drafts,
                items=[AgentTimelineClipItem(video_path=self._video(tmp, "a.mp4"), time_sec=5.0)],
            )
            payload = execute_agent_timeline_export(body)
        self.assertEqual(payload["format"], "jianying")
        self.assertEqual(payload["draft_name"], "VideoSeek导入-1")
        self.assertEqual(payload["clip_count"], 1)
        self.assertEqual(payload["export_path"], draft_path)
        self.assertEqual(payload["meta"]["input"], 1)
        self.assertEqual(payload["meta"]["kept"], 1)
        self.assertEqual(payload["meta"]["dropped"], 0)
        mock_export.assert_called_once()
        self.assertIsNone(mock_export.call_args.kwargs.get("audio"))

    @patch(
        "src.services.jianying_draft_service.export_shot_list_to_jianying_draft",
    )
    @patch(
        "src.services.jianying_draft_service.is_jianying_draft_support_available",
        return_value=True,
    )
    def test_jianying_expands_a_plan(self, _avail, mock_export):
        with tempfile.TemporaryDirectory() as tmp:
            video = self._video(tmp, "a.mp4")
            mock_export.return_value = {
                "draft_name": "cut",
                "drafts_dir": tmp,
                "draft_path": tmp,
                "exported_count": 3,
                "skipped": [],
            }
            body = AgentTimelineExportRequest(
                format="jianying",
                drafts_dir=tmp,
                plan=AgentTimelinePlan(
                    bpm=120.0,
                    beats_per_cut=2,
                    total_sec=3.0,
                    fit_chunk=True,
                    shots=[
                        AgentTimelinePlanShot(video_path=video, start_sec=1.0, end_sec=2.0),
                    ],
                ),
            )
            payload = execute_agent_timeline_export(body)
        shots = mock_export.call_args.args[0]
        self.assertEqual(len(shots), 3)
        self.assertAlmostEqual(shots[0].end_sec - shots[0].start_sec, 1.0)
        self.assertEqual(payload["meta"]["plan"]["expanded_count"], 3)
        self.assertEqual(payload["meta"]["kept"], 3)
        self.assertFalse(payload["meta"]["dedupe"])

    @patch(
        "src.services.jianying_draft_service.export_shot_list_to_jianying_draft",
    )
    @patch(
        "src.services.jianying_draft_service.is_jianying_draft_support_available",
        return_value=True,
    )
    def test_jianying_dedupes_near_starts(self, _avail, mock_export):
        with tempfile.TemporaryDirectory() as tmp:
            video = self._video(tmp, "a.mp4")
            mock_export.return_value = {
                "draft_name": "cut",
                "drafts_dir": tmp,
                "draft_path": tmp,
                "exported_count": 1,
                "skipped": [],
            }
            body = AgentTimelineExportRequest(
                format="jianying",
                drafts_dir=tmp,
                items=[
                    AgentTimelineClipItem(video_path=video, start_sec=10.0, end_sec=16.0),
                    AgentTimelineClipItem(video_path=video, start_sec=10.5, end_sec=20.0),
                ],
            )
            payload = execute_agent_timeline_export(body)
        self.assertEqual(payload["meta"]["input"], 2)
        self.assertEqual(payload["meta"]["kept"], 1)
        self.assertEqual(payload["meta"]["dropped"], 1)
        self.assertEqual(len(mock_export.call_args.args[0]), 1)
        self.assertAlmostEqual(mock_export.call_args.args[0][0].end_sec, 16.0)

    @patch(
        "src.services.jianying_draft_service.export_shot_list_to_jianying_draft",
    )
    @patch(
        "src.services.jianying_draft_service.is_jianying_draft_support_available",
        return_value=True,
    )
    def test_jianying_forwards_audio(self, _avail, mock_export):
        with tempfile.TemporaryDirectory() as tmp:
            music = os.path.join(tmp, "bed.mp3")
            with open(music, "wb") as handle:
                handle.write(b"fake")
            mock_export.return_value = {
                "draft_name": "cut",
                "drafts_dir": tmp,
                "draft_path": tmp,
                "exported_count": 1,
                "skipped": [],
                "audio": {"path": music, "duration_sec": 5.0},
            }
            body = AgentTimelineExportRequest(
                format="jianying",
                drafts_dir=tmp,
                items=[AgentTimelineClipItem(video_path=self._video(tmp, "a.mp4"), time_sec=5.0)],
                audio=AgentTimelineAudio(path=music, fade_out_sec=2.0),
            )
            payload = execute_agent_timeline_export(body)
        forwarded = mock_export.call_args.kwargs["audio"]
        self.assertEqual(forwarded["path"], music)
        self.assertEqual(forwarded["start_sec"], 0.0)
        self.assertEqual(forwarded["fade_out_sec"], 2.0)
        self.assertEqual(payload["audio"]["duration_sec"], 5.0)


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
