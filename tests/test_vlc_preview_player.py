import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")


class VlcSameFileSeekTests(unittest.TestCase):
    def _player(self):
        from PySide6.QtWidgets import QApplication, QWidget

        from ui.playback.vlc_player import VlcPreviewPlayer

        if QApplication.instance() is None:
            self._app = QApplication([])
        host = QWidget()
        self.addCleanup(host.deleteLater)
        mock_mp = MagicMock()
        mock_mp.play.return_value = 0
        mock_mp.get_time.return_value = 40000
        mock_mp.get_length.return_value = 120000
        mock_mp.is_playing.return_value = True
        mock_instance = MagicMock()
        mock_instance.media_player_new.return_value = mock_mp
        mock_instance.media_new.return_value = MagicMock()
        player = VlcPreviewPlayer(host, shared_instance=mock_instance)
        player._owns_instance = False
        return player, mock_mp, mock_instance

    @patch("ui.playback.vlc_player.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    def test_play_same_file_seeks_without_media_new(self, _mock_timer):
        player, mock_mp, mock_instance = self._player()
        self.assertTrue(player.play("D:/videos/clip.mp4", 10.0, stop_sec=16.0))
        self.assertEqual(mock_instance.media_new.call_count, 1)

        mock_instance.media_new.reset_mock()
        mock_mp.set_time.reset_mock()
        self.assertTrue(player.play("D:/videos/clip.mp4", 40.0, stop_sec=46.0))
        mock_instance.media_new.assert_not_called()
        mock_mp.set_time.assert_called()

    @patch("ui.playback.vlc_player.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    def test_play_same_file_reloads_when_seek_is_before_start_time(self, _mock_timer):
        player, _mock_mp, mock_instance = self._player()
        self.assertTrue(player.play("D:/videos/clip.mp4", 40.0, stop_sec=46.0))
        mock_instance.media_new.reset_mock()
        self.assertTrue(player.play("D:/videos/clip.mp4", 5.0, stop_sec=11.0))
        mock_instance.media_new.assert_called_once()

    @patch("ui.playback.vlc_player.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    def test_play_early_clip_rewinds_to_zero_on_reuse(self, _mock_timer):
        """Hits in the first ~6s open from 0; replay must seek to 0, not resume at clip end."""
        player, mock_mp, mock_instance = self._player()
        self.assertTrue(player.play("D:/videos/clip.mp4", 0.0, stop_sec=6.0))
        options = mock_instance.media_new.call_args[0][1:]
        self.assertFalse(any(str(opt).startswith(":start-time=") for opt in options))

        mock_instance.media_new.reset_mock()
        mock_mp.set_time.reset_mock()
        mock_mp.get_time.return_value = 0
        self.assertTrue(player.play("D:/videos/clip.mp4", 0.0, stop_sec=6.0))
        mock_instance.media_new.assert_not_called()
        mock_mp.set_time.assert_called()
        self.assertEqual(mock_mp.set_time.call_args[0][0], 0)


class PreviewSurfaceIdleTests(unittest.TestCase):
    def test_stop_preview_covers_vlc_frame_with_placeholder(self):
        from ui.controllers.preview_controller import PreviewController

        parent = MagicMock()
        parent.video_widget = MagicMock()
        parent.search_page.preview_placeholder = MagicMock()
        parent.preview_surface_stack = MagicMock()
        parent.media_player = MagicMock()
        controller = PreviewController(parent)
        controller.vlc_player = MagicMock()
        controller.vlc_player.is_available.return_value = True

        controller.stop_preview(skip_telemetry=True)

        controller.vlc_player.clear_session.assert_called_once()
        parent.preview_surface_stack.setCurrentWidget.assert_called_with(
            parent.search_page.preview_placeholder
        )
