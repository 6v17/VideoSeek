import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import utils


class FormatTimecodeTests(unittest.TestCase):
    def test_format_timecode_seconds_under_one_hour(self):
        self.assertEqual(utils.format_timecode_seconds(0), "00:00")
        self.assertEqual(utils.format_timecode_seconds(65), "01:05")
        self.assertEqual(utils.format_timecode_seconds(3599), "59:59")

    def test_format_timecode_seconds_one_hour_or_more(self):
        self.assertEqual(utils.format_timecode_seconds(3600), "1:00:00")
        self.assertEqual(utils.format_timecode_seconds(3665), "1:01:05")

    def test_format_timecode_seconds_accepts_string_input(self):
        self.assertEqual(utils.format_timecode_seconds("90.9"), "01:30")

    def test_format_timecode_range_single_point(self):
        self.assertEqual(utils.format_timecode_range(12.0, 12.1), "00:12")

    def test_format_timecode_range_span(self):
        self.assertEqual(utils.format_timecode_range(12.0, 18.0), "00:12–00:18")


class ExportEncodeModeTests(unittest.TestCase):
    def test_normalize_export_encode_mode(self):
        self.assertEqual(utils.normalize_export_encode_mode("copy"), utils.EXPORT_ENCODE_MODE_COPY)
        self.assertEqual(utils.normalize_export_encode_mode("stream_copy"), utils.EXPORT_ENCODE_MODE_COPY)
        self.assertEqual(utils.normalize_export_encode_mode(None), utils.EXPORT_ENCODE_MODE_ORIGINAL)
        self.assertEqual(utils.normalize_export_encode_mode("original"), utils.EXPORT_ENCODE_MODE_ORIGINAL)


class ResolveFfmpegPathInfoTests(unittest.TestCase):
    @patch("src.utils.shutil.which", return_value=None)
    @patch("src.utils.os.path.exists", return_value=False)
    @patch("src.utils.get_configured_ffmpeg_target_path", return_value="D:/cfg/ffmpeg.exe")
    @patch("src.app.config.load_config", return_value={})
    def test_resolve_ffmpeg_path_info_missing(
        self,
        _mock_load_config,
        _mock_configured_path,
        _mock_exists,
        _mock_which,
    ):
        path, source = utils.resolve_ffmpeg_path_info()

        self.assertEqual(path, "")
        self.assertEqual(source, "missing")

    @patch("src.utils.shutil.which", return_value="/usr/bin/ffmpeg")
    @patch("src.utils.os.path.exists", return_value=False)
    @patch("src.utils.get_configured_ffmpeg_target_path", return_value="D:/cfg/ffmpeg.exe")
    @patch("src.app.config.load_config", return_value={})
    def test_resolve_ffmpeg_path_info_falls_back_to_system_path(
        self,
        _mock_load_config,
        _mock_configured_path,
        _mock_exists,
        _mock_which,
    ):
        path, source = utils.resolve_ffmpeg_path_info()

        self.assertEqual(path, "/usr/bin/ffmpeg")
        self.assertEqual(source, "system")

    @patch("src.utils.os.path.exists")
    @patch("src.utils.get_configured_ffmpeg_target_path", return_value="D:/cfg/ffmpeg.exe")
    @patch("src.app.config.load_config", return_value={"ffmpeg_path": "D:/cfg/ffmpeg.exe"})
    def test_resolve_ffmpeg_path_info_prefers_configured_path(
        self,
        _mock_load_config,
        _mock_configured_path,
        mock_exists,
    ):
        mock_exists.side_effect = lambda path: os.path.normcase(path) == os.path.normcase("D:/cfg/ffmpeg.exe")

        path, source = utils.resolve_ffmpeg_path_info()

        self.assertEqual(path, "D:/cfg/ffmpeg.exe")
        self.assertEqual(source, "configured")


class PreviewClipEncodeConfigTests(unittest.TestCase):
    @patch("src.utils.subprocess.run")
    @patch("src.utils.get_ffmpeg_path", return_value="ffmpeg")
    @patch(
        "src.app.config.load_config",
        return_value={
            "preview_seconds": 6,
            "preview_width": 640,
            "preview_height": 360,
            "preview_encode_preset": "veryfast",
            "preview_encode_tune": "film",
            "preview_encode_crf": 28,
            "preview_encode_audio_bitrate": "96k",
        },
    )
    @patch("src.utils.os.path.exists", return_value=False)
    def test_create_preview_clip_uses_configured_encode_settings(
        self,
        _mock_exists,
        _mock_load_config,
        _mock_get_ffmpeg,
        mock_run,
    ):
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        utils.create_preview_clip("D:/videos/clip.mp4", 10.0, "D:/cache/p.mp4")

        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("-preset") + 1], "veryfast")
        self.assertEqual(cmd[cmd.index("-tune") + 1], "film")
        self.assertEqual(cmd[cmd.index("-crf") + 1], "28")
        self.assertEqual(cmd[cmd.index("-b:a") + 1], "96k")


class ExportClipEncodeConfigTests(unittest.TestCase):
    @patch("src.utils.get_ffmpeg_path", return_value="ffmpeg")
    @patch("src.utils.ensure_folder_exists")
    @patch("src.utils.os.path.exists", return_value=False)
    def test_build_export_original_clip_command_uses_configured_encode_settings(
        self,
        _mock_exists,
        _mock_ensure_folder_exists,
        _mock_get_ffmpeg,
    ):
        config = {
            "export_encode_preset": "medium",
            "export_encode_crf": 20,
            "export_encode_audio_bitrate": "160k",
        }

        cmd = utils.build_export_original_clip_command(
            "D:/videos/clip.mp4",
            8.0,
            3.5,
            "D:/out/clip.mp4",
            config=config,
        )

        self.assertEqual(cmd[cmd.index("-preset") + 1], "medium")
        self.assertEqual(cmd[cmd.index("-crf") + 1], "20")
        self.assertEqual(cmd[cmd.index("-b:a") + 1], "160k")


class CanonicalizeLibraryPathTests(unittest.TestCase):
    def test_canonicalize_library_path_normalizes_separators_and_case(self):
        with patch("src.utils.os.name", "nt"):
            result = utils.canonicalize_library_path("D:/Videos\\Demo")

        self.assertEqual(result, os.path.normcase(os.path.normpath("D:/Videos/Demo")))


class BuildPreviewCachePathTests(unittest.TestCase):
    def test_build_preview_cache_path_is_deterministic_for_same_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = str(Path(temp_dir) / "clip.mp4")
            first = utils.build_preview_cache_path(video_path, 12.5)
            second = utils.build_preview_cache_path(video_path, 12.5)

        self.assertNotEqual(first, second)
        self.assertTrue(first.endswith(".mp4"))
        self.assertTrue(second.endswith(".mp4"))


if __name__ == "__main__":
    unittest.main()
