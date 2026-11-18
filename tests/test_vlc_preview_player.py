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
        host.resize(320, 180)
        host.show()
        self.addCleanup(host.close)
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

    @patch("ui.playback.vlc_player.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    def test_pending_seek_does_not_repeat_set_time(self, _mock_timer):
        """Repeating set_time while the clock is still ahead restarts a backward seek."""
        player, mock_mp, mock_instance = self._player()
        self.assertTrue(player.play("D:/videos/clip.mp4", 10.0, stop_sec=16.0))
        mock_instance.media_new.reset_mock()
        mock_mp.set_time.reset_mock()
        mock_mp.get_time.return_value = 40000

        self.assertTrue(player.play("D:/videos/clip.mp4", 20.0, stop_sec=26.0))

        mock_instance.media_new.assert_not_called()
        self.assertEqual(mock_mp.set_time.call_count, 1)
        self.assertEqual(mock_mp.set_time.call_args[0][0], 20000)

    @patch("ui.playback.vlc_player.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    def test_set_time_before_origin_reopens_without_bouncing(self, _mock_timer):
        player, mock_mp, mock_instance = self._player()
        self.assertTrue(player.play("D:/videos/clip.mp4", 40.0, stop_sec=46.0))
        mock_instance.media_new.reset_mock()
        mock_mp.set_time.reset_mock()
        mock_mp.set_pause.reset_mock()
        mock_mp.get_time.return_value = 42000

        player.set_time(5000, unlock=True)

        mock_instance.media_new.assert_called_once()
        options = mock_instance.media_new.call_args[0][1:]
        self.assertFalse(any(str(opt).startswith(":start-time=") for opt in options))
        self.assertIn(5000, [call.args[0] for call in mock_mp.set_time.call_args_list])
        mock_mp.set_pause.assert_not_called()

    @patch("ui.playback.vlc_player.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    def test_set_time_after_origin_does_not_reload(self, _mock_timer):
        player, mock_mp, mock_instance = self._player()
        self.assertTrue(player.play("D:/videos/clip.mp4", 40.0, stop_sec=46.0))
        mock_instance.media_new.reset_mock()
        mock_mp.set_time.reset_mock()

        player.set_time(45000, unlock=True)

        mock_instance.media_new.assert_not_called()
        mock_mp.set_time.assert_called_once_with(45000)

    @patch("ui.playback.vlc_player.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    def test_play_between_keyframes_opens_on_the_previous_one(self, _mock_timer):
        import tempfile

        from tests.test_mp4_sync import _write_sync_mp4

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "clip.mp4")
        _write_sync_mp4(path)
        self.addCleanup(lambda: os.remove(path))

        player, _mock_mp, mock_instance = self._player()
        self.assertTrue(player.play(path, 12.0, stop_sec=18.0))
        options = [str(item) for item in mock_instance.media_new.call_args[0][1:]]
        self.assertIn(":start-time=8.000", options)
        self.assertEqual(player._media_origin_sec, 8.0)
        self.assertIn(12000, [call.args[0] for call in _mock_mp.set_time.call_args_list])
        _mock_mp.set_rate.assert_not_called()
        mock_instance.media_new.reset_mock()
        _mock_mp.set_time.reset_mock()
        self.assertEqual(player.set_time(14000), 8000)
        options = [str(item) for item in mock_instance.media_new.call_args[0][1:]]
        self.assertIn(":start-time=8.000", options)
        _mock_mp.set_time.assert_not_called()

    @patch("ui.playback.vlc_player.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    def test_reverse_reopen_snaps_to_a_keyframe(self, _mock_timer):
        import tempfile

        from tests.test_mp4_sync import _write_gop_mp4

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "clip.mp4")
        _write_gop_mp4(path, 50, [1, 21, 41])
        self.addCleanup(lambda: os.remove(path))

        player, mock_mp, mock_instance = self._player()
        self.assertTrue(player.play(path, 44.0, stop_sec=50.0))
        options = [str(item) for item in mock_instance.media_new.call_args[0][1:]]
        self.assertIn(":start-time=40.000", options)
        self.assertIn(44000, [call.args[0] for call in mock_mp.set_time.call_args_list])

        mock_instance.media_new.reset_mock()
        mock_mp.set_time.reset_mock()
        mock_mp.get_time.return_value = 40000
        self.assertEqual(player.set_time(20050), 20050)
        options = [str(item) for item in mock_instance.media_new.call_args[0][1:]]
        self.assertFalse(any(item.startswith(":start-time=") for item in options))
        self.assertIn(20050, [call.args[0] for call in mock_mp.set_time.call_args_list])

    @patch("ui.playback.vlc_player.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    def test_play_waits_for_the_background_index(self, _mock_timer):
        import tempfile

        from src.media.mp4_sync import ensure_sync_index
        from tests.test_mp4_sync import _write_sync_mp4

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "clip.mp4")
        _write_sync_mp4(path)
        self.addCleanup(lambda: os.remove(path))
        saved = os.environ.pop("VIDEOSEEK_TEST_MODE", None)
        self.addCleanup(lambda: os.environ.__setitem__("VIDEOSEEK_TEST_MODE", saved or "1"))
        captured = {}

        def _capture(ready_path, on_ready):
            captured["path"] = ready_path
            captured["callback"] = on_ready

        player, _mock_mp, mock_instance = self._player()
        with patch("src.media.mp4_sync.schedule_sync_index", side_effect=_capture):
            self.assertTrue(player.play(path, 12.0, stop_sec=18.0))
            self.assertTrue(player._waiting_for_sync_index)
        mock_instance.media_new.assert_not_called()
        ensure_sync_index(captured["path"])
        captured["callback"](captured["path"])
        options = [str(item) for item in mock_instance.media_new.call_args[0][1:]]
        self.assertIn(":start-time=8.000", options)

    @patch("ui.playback.vlc_player.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    def test_fragmented_file_opens_on_time_with_avformat(self, _mock_timer):
        import tempfile

        from tests.test_mp4_sync import _write_sync_mp4

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "clip.mp4")
        _write_sync_mp4(path)
        self.addCleanup(lambda: os.remove(path))
        player, mock_mp, mock_instance = self._player()
        with patch("ui.playback.vlc_player._is_fragmented_mp4", return_value=True):
            self.assertTrue(player.play(path, 12.0, stop_sec=18.0))
            self.assertEqual(
                mock_instance.media_new.call_args[0][0],
                os.path.normcase(os.path.normpath(path)),
            )
            options = [str(item) for item in mock_instance.media_new.call_args[0][1:]]
            self.assertIn(":demux=avformat", options)
            self.assertIn(":start-time=12.000", options)
            self.assertEqual(player._stop_at_ms, 18000)
            mock_mp.set_rate.assert_not_called()
            mock_instance.media_new.reset_mock()
            mock_mp.set_time.reset_mock()
            self.assertEqual(player.set_time(14000), 14000)
            mock_mp.set_time.assert_called_once_with(14000)
            mock_instance.media_new.assert_not_called()


class VlcResumeSeekTests(unittest.TestCase):
    def _player(self):
        from PySide6.QtWidgets import QApplication, QWidget

        from ui.playback.vlc_player import VlcPreviewPlayer

        if QApplication.instance() is None:
            self._app = QApplication([])
        host = QWidget()
        host.resize(320, 180)
        host.show()
        self.addCleanup(host.close)
        self.addCleanup(host.deleteLater)
        mock_mp = MagicMock()
        mock_mp.play.return_value = 0
        mock_mp.get_time.return_value = 12000
        mock_mp.get_length.return_value = 120000
        mock_mp.is_playing.return_value = False
        mock_instance = MagicMock()
        mock_instance.media_player_new.return_value = mock_mp
        mock_instance.media_new.return_value = MagicMock()
        player = VlcPreviewPlayer(host, shared_instance=mock_instance)
        player._owns_instance = False
        return player, mock_mp, mock_instance

    @patch("ui.playback.vlc_player.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    def test_resume_after_set_time_does_not_reload_media(self, _mock_timer):
        player, mock_mp, mock_instance = self._player()
        self.assertTrue(player.play("D:/videos/clip.mp4", 10.0, stop_sec=16.0))
        mock_instance.media_new.reset_mock()
        mock_mp.set_time.reset_mock()

        player.set_time(15000, unlock=True)
        self.assertTrue(player.resume())

        mock_instance.media_new.assert_not_called()
        mock_mp.set_time.assert_called()
        mock_mp.play.assert_called()


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
