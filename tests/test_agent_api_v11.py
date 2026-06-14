import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

if "faiss" not in sys.modules:
    sys.modules["faiss"] = MagicMock()

if "src.services.library_service" not in sys.modules:
    _fake_library_service = types.ModuleType("src.services.library_service")
    _fake_library_service.list_libraries = MagicMock(return_value={})
    sys.modules["src.services.library_service"] = _fake_library_service

if "src.storage" not in sys.modules:
    sys.modules["src.storage"] = types.ModuleType("src.storage")
if "src.storage.config_store" not in sys.modules:
    _fake_config_store = types.ModuleType("src.storage.config_store")
    _fake_config_store.get_search_scope_mode = MagicMock(return_value="all")
    sys.modules["src.storage.config_store"] = _fake_config_store
if "src.storage.asset_store" not in sys.modules:
    _fake_asset_store = types.ModuleType("src.storage.asset_store")
    _fake_asset_store.load_model_metadata = MagicMock(return_value={})
    sys.modules["src.storage.asset_store"] = _fake_asset_store

from types import SimpleNamespace

from src.services.agent_clip_service import execute_agent_batch_export_clips, execute_agent_export_clip, resolve_clip_window
from src.utils import EXPORT_ENCODE_MODE_COPY, EXPORT_ENCODE_MODE_ORIGINAL, resolve_export_clip_window
from src.services.agent_library_service import list_agent_libraries, list_agent_library_videos


class AgentLibraryServiceTests(unittest.TestCase):
    @patch("src.storage.config_store.get_search_scope_mode", return_value="all")
    @patch("src.services.agent_library_service.get_search_index_schema_version", return_value=2)
    @patch("src.services.agent_library_service.list_library_search_index_summaries", return_value=[])
    @patch("src.services.agent_library_service.library_index_is_ready", return_value=False)
    @patch("src.storage.asset_store.load_model_metadata", return_value={})
    @patch("src.services.library_service.list_libraries")
    def test_list_agent_libraries(self, mock_list_libraries, *_mocks):
        mock_list_libraries.return_value = {
            "D:/Anime": {
                "index_state": "ready",
                "files": {
                    "ep01.mp4": {"vid": "v1", "asset_state": "ready"},
                    "ep02.mp4": {"vid": "v2", "asset_state": "missing_source"},
                },
            }
        }
        payload = list_agent_libraries()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["meta"]["count"], 1)
        lib = payload["libraries"][0]
        self.assertEqual(lib["library_path"], "D:/Anime")
        self.assertEqual(lib["display_name"], "Anime")
        self.assertEqual(lib["video_count_total"], 2)
        self.assertEqual(lib["video_count_indexed_ready"], 1)

    @patch("src.services.library_service.list_libraries")
    def test_list_agent_library_videos_ready_only(self, mock_list_libraries):
        with tempfile.TemporaryDirectory() as lib_dir:
            ready_file = os.path.join(lib_dir, "keep.mp4")
            with open(ready_file, "wb") as handle:
                handle.write(b"0")
            mock_list_libraries.return_value = {
                lib_dir: {
                    "files": {
                        "keep.mp4": {"vid": "v1", "asset_state": "ready"},
                        "gone.mp4": {"vid": "v2", "asset_state": "ready"},
                    }
                }
            }
            payload = list_agent_library_videos(lib_dir, ready_only=True, limit=10, offset=0)
            self.assertTrue(payload["ok"])
            self.assertEqual(len(payload["videos"]), 1)
            self.assertEqual(payload["videos"][0]["video_path"], ready_file)

    @patch("src.services.library_service.list_libraries", return_value={})
    def test_list_agent_library_videos_unknown_library(self, _mock_libraries):
        with self.assertRaises(KeyError):
            list_agent_library_videos("D:/missing")


class AgentClipServiceTests(unittest.TestCase):
    def test_resolve_clip_window_with_end(self):
        clip_start, clip_duration = resolve_clip_window(
            "D:/a.mp4",
            10.0,
            end_sec=15.0,
            encode_mode=EXPORT_ENCODE_MODE_ORIGINAL,
        )
        self.assertEqual(clip_start, 10.0)
        self.assertEqual(clip_duration, 5.0)

    def test_resolve_clip_window_copy_extends_range(self):
        config = {
            "preview_seconds": 6,
            "export_copy_extra_sec": 4,
            "export_copy_margin_sec": 2.0,
        }
        clip_start, clip_duration = resolve_clip_window(
            "D:/a.mp4",
            10.0,
            end_sec=15.0,
            config=config,
            encode_mode=EXPORT_ENCODE_MODE_COPY,
        )
        self.assertEqual(clip_start, 8.0)
        self.assertEqual(clip_duration, 9.0)

    def test_resolve_export_clip_window_copy_center_extra(self):
        config = {"preview_seconds": 6, "export_copy_extra_sec": 4, "export_copy_margin_sec": 2.0}
        clip_start, clip_duration = resolve_export_clip_window(
            "D:/a.mp4",
            10.0,
            config=config,
            encode_mode=EXPORT_ENCODE_MODE_COPY,
        )
        self.assertEqual(clip_duration, 10.0)

    @patch("src.services.agent_clip_service._output_path_allowed", return_value=True)
    @patch("src.utils.has_ffmpeg", return_value=True)
    @patch("src.services.agent_clip_service.export_original_clip")
    @patch("src.utils.get_video_duration_seconds", return_value=100.0)
    def test_execute_agent_export_clip(self, _duration, mock_export, _ffmpeg, _allowed):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "src.mp4")
            output = os.path.join(tmp, "out.mp4")
            with open(source, "wb") as handle:
                handle.write(b"0")
            mock_export.return_value = type("R", (), {"returncode": 0, "stderr": b""})()
            payload = execute_agent_export_clip(
                video_path=source,
                start_sec=1.0,
                end_sec=4.0,
                output_path=output,
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["output_path"], output)
            self.assertEqual(payload["encode_mode"], "copy")
            mock_export.assert_called_once()
            self.assertEqual(mock_export.call_args.kwargs.get("encode_mode"), "copy")

    @patch("src.services.agent_clip_service._output_path_allowed", return_value=True)
    @patch("src.utils.has_ffmpeg", return_value=True)
    @patch("src.services.agent_clip_service.export_original_clip")
    @patch("src.services.agent_clip_service.resolve_clip_window", return_value=(10.0, 6.0))
    def test_execute_agent_export_clip_frame_point(self, mock_window, mock_export, _ffmpeg, _allowed):
        mock_export.return_value = type("R", (), {"returncode": 0, "stderr": b""})()
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "src.mp4")
            output = os.path.join(tmp, "out.mp4")
            with open(source, "wb") as handle:
                handle.write(b"0")
            payload = execute_agent_export_clip(
                video_path=source,
                start_sec=12.0,
                end_sec=12.0,
                output_path=output,
                encode_mode="copy",
            )
        self.assertTrue(payload["ok"])
        mock_window.assert_called_once()
        self.assertIsNone(mock_window.call_args.kwargs.get("end_sec"))

    @patch("src.services.agent_clip_service._output_path_allowed", return_value=True)
    @patch("src.utils.has_ffmpeg", return_value=True)
    @patch("src.services.agent_clip_service.execute_agent_export_clip")
    def test_execute_agent_batch_export_clips(self, mock_export, _ffmpeg, _allowed):
        mock_export.side_effect = lambda **kwargs: {
            "output_path": kwargs["output_path"],
            "client_request_id": kwargs.get("client_request_id"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "src.mp4")
            with open(source, "wb") as handle:
                handle.write(b"0")
            body = SimpleNamespace(
                encode_mode="copy",
                silent=None,
                continue_on_error=True,
                items=[
                    SimpleNamespace(
                        client_request_id="a",
                        video_path=source,
                        start_sec=1.0,
                        end_sec=4.0,
                        output_path=os.path.join(tmp, "a.mp4"),
                        encode_mode=None,
                        silent=None,
                    ),
                    SimpleNamespace(
                        client_request_id="b",
                        video_path=source,
                        start_sec=5.0,
                        end_sec=8.0,
                        output_path=os.path.join(tmp, "b.mp4"),
                        encode_mode=None,
                        silent=None,
                    ),
                ],
            )
            payload = execute_agent_batch_export_clips(body)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["meta"]["succeeded"], 2)
            self.assertEqual(len(payload["results"]), 2)
            self.assertEqual(mock_export.call_count, 2)

    @patch("src.services.agent_clip_service._output_path_allowed", return_value=True)
    @patch("src.utils.has_ffmpeg", return_value=True)
    @patch("src.services.agent_clip_service.execute_agent_export_clip")
    def test_execute_agent_batch_export_clips_partial_failure(self, mock_export, _ffmpeg, _allowed):
        def side_effect(**kwargs):
            if kwargs.get("start_sec") == 5.0:
                raise ValueError("bad range")
            return {"ok": True, "output_path": kwargs["output_path"]}

        mock_export.side_effect = side_effect
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "src.mp4")
            with open(source, "wb") as handle:
                handle.write(b"0")
            body = SimpleNamespace(
                encode_mode=None,
                silent=None,
                continue_on_error=True,
                items=[
                    SimpleNamespace(
                        client_request_id=None,
                        video_path=source,
                        start_sec=1.0,
                        end_sec=4.0,
                        output_path=os.path.join(tmp, "a.mp4"),
                        encode_mode=None,
                        silent=None,
                    ),
                    SimpleNamespace(
                        client_request_id=None,
                        video_path=source,
                        start_sec=5.0,
                        end_sec=4.0,
                        output_path=os.path.join(tmp, "b.mp4"),
                        encode_mode=None,
                        silent=None,
                    ),
                ],
            )
            payload = execute_agent_batch_export_clips(body)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["meta"]["succeeded"], 1)
            self.assertEqual(payload["meta"]["failed"], 1)
            self.assertFalse(payload["results"][1]["ok"])

    @patch("src.services.agent_clip_service._output_path_allowed", return_value=False)
    def test_execute_agent_export_clip_rejects_library_output(self, _allowed):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "src.mp4")
            with open(source, "wb") as handle:
                handle.write(b"0")
            with self.assertRaises(ValueError):
                execute_agent_export_clip(
                    video_path=source,
                    start_sec=1.0,
                    end_sec=4.0,
                    output_path=os.path.join("D:/Lib", "out.mp4"),
                )


if __name__ == "__main__":
    unittest.main()
