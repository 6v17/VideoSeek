import unittest
from unittest.mock import MagicMock, patch

from src.media import export_clip as utils


class SeekablePreviewProxyFastPathTests(unittest.TestCase):
    def test_mp4_is_ready_without_ffmpeg(self):
        self.assertEqual(
            utils.get_seekable_preview_proxy_if_ready("D:/videos/clip.mp4"),
            "D:/videos/clip.mp4",
        )

    def test_http_is_ready_without_ffmpeg(self):
        url = "http://192.168.1.2:18080/videos/a.mpg"
        self.assertEqual(utils.get_seekable_preview_proxy_if_ready(url), url)

    @patch("src.media.export_clip.os.path.isfile", return_value=True)
    @patch("src.media.export_clip.os.path.getsize", return_value=10_000)
    @patch(
        "src.media.export_clip.build_seekable_preview_proxy_path",
        return_value="D:/cache/seek_proxy/proxy_abc.mp4",
    )
    def test_cached_mpg_proxy_is_ready(self, _mock_path, mock_getsize, _mock_isfile):
        mock_getsize.side_effect = lambda p: 10_000 if str(p).endswith(".mpg") else 9_500
        out = utils.get_seekable_preview_proxy_if_ready("D:/videos/show.mpg")
        self.assertEqual(out, "D:/cache/seek_proxy/proxy_abc.mp4")

    @patch("src.media.export_clip.os.path.isfile")
    @patch("src.media.export_clip.os.path.getsize", return_value=10_000)
    @patch(
        "src.media.export_clip.build_seekable_preview_proxy_path",
        return_value="D:/cache/seek_proxy/proxy_abc.mp4",
    )
    def test_uncached_mpg_needs_ffmpeg(self, _mock_path, _mock_getsize, mock_isfile):
        def _isfile(p):
            return str(p).endswith(".mpg")

        mock_isfile.side_effect = _isfile
        self.assertIsNone(utils.get_seekable_preview_proxy_if_ready("D:/videos/show.mpg"))


class PreviewControllerPrepareTests(unittest.TestCase):
    def _parent(self):
        parent = MagicMock()
        parent.search_page = MagicMock()
        parent.search_page.preview_collapsed = False
        parent.media_player = MagicMock()
        parent.video_widget = MagicMock()
        parent.preview_video_host = None
        parent.preview_surface_stack = MagicMock()
        return parent

    @patch("ui.controllers.preview_controller.create_vlc_preview_instance", return_value=None)
    @patch("src.media.export_clip.resolve_base_clip_window", return_value=(27.0, 6.0))
    @patch("ui.controllers.preview_controller.VlcPreviewPlayer")
    def test_play_mp4_stays_on_fast_path(self, mock_vlc_cls, _window, _instance):
        from ui.controllers.preview_controller import PreviewController

        parent = self._parent()
        vlc_player = MagicMock()
        vlc_player.play.return_value = True
        mock_vlc_cls.return_value = vlc_player
        controller = PreviewController(parent)

        with patch("src.media.export_clip.get_seekable_preview_proxy_if_ready", return_value="D:/videos/clip.mp4") as peek:
            with patch("ui.playback.preview_prepare_worker.PreviewPrepareWorker") as worker_cls:
                result = controller.play("D:/videos/clip.mp4", 30.0)
                self.assertTrue(result)
                peek.assert_called_once()
                worker_cls.assert_not_called()
                vlc_player.play.assert_called_once_with("D:/videos/clip.mp4", 27.0, stop_sec=33.0)

    @patch("ui.controllers.preview_controller.create_vlc_preview_instance", return_value=None)
    @patch("src.media.export_clip.resolve_base_clip_window", return_value=(27.0, 6.0))
    def test_play_uncached_mpg_starts_proxy_worker(self, _window, _instance):
        from ui.controllers.preview_controller import PreviewController

        parent = self._parent()
        controller = PreviewController(parent)
        fake_worker = MagicMock()
        fake_worker.isRunning.return_value = False

        with patch("src.media.export_clip.get_seekable_preview_proxy_if_ready", return_value=None):
            with patch(
                "ui.playback.preview_prepare_worker.PreviewPrepareWorker",
                return_value=fake_worker,
            ) as worker_cls:
                result = controller.play("D:/videos/show.mpg", 30.0)
                self.assertTrue(result)
                worker_cls.assert_called_once()
                kwargs = worker_cls.call_args.kwargs
                self.assertEqual(kwargs.get("mode"), "proxy")
                fake_worker.start.assert_called_once()

    @patch("ui.controllers.preview_controller.create_vlc_preview_instance", return_value=None)
    @patch("src.media.export_clip.build_preview_cache_path", return_value="D:/cache/preview.mp4")
    @patch("src.media.export_clip.resolve_base_clip_window", return_value=(27.0, 6.0))
    @patch("ui.controllers.preview_controller.VlcPreviewPlayer")
    def test_play_vlc_fail_starts_clip_worker(self, mock_vlc_cls, _window, _cache, _instance):
        from ui.controllers.preview_controller import PreviewController

        parent = self._parent()
        vlc_player = MagicMock()
        vlc_player.play.return_value = False
        mock_vlc_cls.return_value = vlc_player
        controller = PreviewController(parent)
        fake_worker = MagicMock()
        fake_worker.isRunning.return_value = False

        with patch("src.media.export_clip.get_seekable_preview_proxy_if_ready", return_value="D:/videos/clip.mp4"):
            with patch(
                "ui.playback.preview_prepare_worker.PreviewPrepareWorker",
                return_value=fake_worker,
            ) as worker_cls:
                result = controller.play("D:/videos/clip.mp4", 30.0)
                self.assertTrue(result)
                worker_cls.assert_called_once()
                kwargs = worker_cls.call_args.kwargs
                self.assertEqual(kwargs.get("mode"), "clip")
                fake_worker.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
