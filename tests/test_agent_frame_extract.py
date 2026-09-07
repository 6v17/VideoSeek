"""Tests for Agent API single-frame extract."""

from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

import numpy as np

from src.web.agent_api.frames import (
    DEFAULT_FRAME_MAX_EDGE,
    execute_agent_frame_extract,
)
from src.web.agent_api.schemas import AgentFrameExtractRequest


class AgentFrameExtractTests(unittest.TestCase):
    @patch("src.media.thumbnail.get_single_thumbnail")
    @patch("src.web.agent_api.frames.os.path.isfile", return_value=True)
    def test_extract_returns_jpeg_base64(self, _mock_isfile, mock_thumb):
        # 100x50 BGR solid frame
        frame = np.zeros((50, 100, 3), dtype=np.uint8)
        frame[:, :] = (0, 128, 255)
        mock_thumb.return_value = frame
        body = AgentFrameExtractRequest(
            video_path="D:/lib/clip.mp4",
            time_sec=12.5,
            client_request_id="hit-1",
        )
        payload = execute_agent_frame_extract(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mime"], "image/jpeg")
        self.assertEqual(payload["client_request_id"], "hit-1")
        self.assertEqual(payload["time_sec"], 12.5)
        self.assertEqual(payload["meta"]["max_edge"], DEFAULT_FRAME_MAX_EDGE)
        raw = base64.b64decode(payload["image_base64"])
        self.assertGreater(len(raw), 32)
        self.assertEqual(payload["width"], 100)
        self.assertEqual(payload["height"], 50)
        mock_thumb.assert_called_once()
        self.assertEqual(mock_thumb.call_args.args[1], 12.5)

    @patch("src.media.thumbnail.get_single_thumbnail")
    @patch("src.web.agent_api.frames.os.path.isfile", return_value=True)
    def test_max_edge_downscales(self, _mock_isfile, mock_thumb):
        frame = np.zeros((2000, 1000, 3), dtype=np.uint8)
        mock_thumb.return_value = frame
        body = AgentFrameExtractRequest(
            video_path="D:/lib/clip.mp4",
            time_sec=1.0,
            max_edge=640,
        )
        payload = execute_agent_frame_extract(body)
        self.assertEqual(payload["meta"]["max_edge"], 640)
        self.assertEqual(payload["height"], 640)
        self.assertEqual(payload["width"], 320)

    @patch("src.web.agent_api.frames.os.path.isfile", return_value=False)
    def test_missing_path_raises(self, _mock_isfile):
        body = AgentFrameExtractRequest(video_path="D:/missing.mp4", time_sec=0.0)
        with self.assertRaises(FileNotFoundError):
            execute_agent_frame_extract(body)

    @patch("src.media.thumbnail.get_single_thumbnail", return_value=None)
    @patch("src.web.agent_api.frames.os.path.isfile", return_value=True)
    def test_thumbnail_failure_raises(self, _mock_isfile, _mock_thumb):
        body = AgentFrameExtractRequest(video_path="D:/lib/clip.mp4", time_sec=3.0)
        with self.assertRaises(RuntimeError):
            execute_agent_frame_extract(body)

    def test_negative_time_clamped_via_execute(self):
        with patch("src.web.agent_api.frames.os.path.isfile", return_value=True), patch(
            "src.media.thumbnail.get_single_thumbnail"
        ) as mock_thumb:
            mock_thumb.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
            body = AgentFrameExtractRequest(video_path="D:/lib/clip.mp4", time_sec=-5.0)
            payload = execute_agent_frame_extract(body)
            self.assertEqual(payload["time_sec"], 0.0)
            self.assertEqual(mock_thumb.call_args.args[1], 0.0)


class AgentFrameExtractHealthTests(unittest.TestCase):
    @patch("src.web.agent_api.health.get_search_scope_mode", return_value="all")
    @patch("src.web.agent_api.health._build_ffmpeg_info")
    @patch("src.web.agent_api.health._index_snapshot")
    @patch("src.web.agent_api.health.get_active_embedding_spec")
    @patch("src.services.library_service.list_libraries", return_value={})
    @patch("src.web.agent_api.health.get_search_mode", return_value="frame")
    def test_health_includes_frame_extract(
        self, _mode, _libs, mock_spec, mock_snapshot, mock_ffmpeg, _scope
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
        self.assertTrue(payload["capabilities"]["frame_extract"])
        self.assertTrue(payload["capabilities"]["batch_frame_extract"])
        self.assertEqual(payload["max_batch_frame_extract"], 16)


class AgentBatchFrameExtractTests(unittest.TestCase):
    @patch("src.media.thumbnail.get_single_thumbnail")
    @patch("src.web.agent_api.frames.os.path.isfile", return_value=True)
    def test_batch_success_and_inherits_max_edge(self, _isfile, mock_thumb):
        from src.web.agent_api.frames import execute_agent_batch_frame_extract
        from src.web.agent_api.schemas import AgentBatchFrameExtractRequest, AgentFrameExtractRequest

        mock_thumb.return_value = np.zeros((800, 400, 3), dtype=np.uint8)
        body = AgentBatchFrameExtractRequest(
            max_edge=200,
            items=[
                AgentFrameExtractRequest(video_path="D:/a.mp4", time_sec=1.0, client_request_id="1"),
                AgentFrameExtractRequest(video_path="D:/b.mp4", time_sec=2.0, client_request_id="2"),
            ],
        )
        payload = execute_agent_batch_frame_extract(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["meta"]["succeeded"], 2)
        self.assertEqual(payload["meta"]["failed"], 0)
        self.assertEqual(len(payload["results"]), 2)
        self.assertEqual(payload["results"][0]["meta"]["max_edge"], 200)
        self.assertLessEqual(payload["results"][0]["height"], 200)

    @patch("src.web.agent_api.frames.os.path.isfile", side_effect=[False, True])
    @patch("src.media.thumbnail.get_single_thumbnail")
    def test_batch_continue_on_error(self, mock_thumb, _isfile):
        from src.web.agent_api.frames import execute_agent_batch_frame_extract
        from src.web.agent_api.schemas import AgentBatchFrameExtractRequest, AgentFrameExtractRequest

        mock_thumb.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
        body = AgentBatchFrameExtractRequest(
            continue_on_error=True,
            items=[
                AgentFrameExtractRequest(video_path="D:/missing.mp4", time_sec=1.0),
                AgentFrameExtractRequest(video_path="D:/ok.mp4", time_sec=2.0),
            ],
        )
        payload = execute_agent_batch_frame_extract(body)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["meta"]["succeeded"], 1)
        self.assertEqual(payload["meta"]["failed"], 1)
        self.assertFalse(payload["results"][0]["ok"])
        self.assertTrue(payload["results"][1]["ok"])

    def test_batch_empty_raises(self):
        from src.web.agent_api.frames import execute_agent_batch_frame_extract
        from src.web.agent_api.schemas import AgentBatchFrameExtractRequest

        with self.assertRaises(ValueError):
            execute_agent_batch_frame_extract(AgentBatchFrameExtractRequest(items=[]))


if __name__ == "__main__":
    unittest.main()
