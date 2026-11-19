import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")


class PreviewKeyboardHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            cls._app = QApplication([])

    def test_floating_preview_top_left_centers_on_frame(self):
        from ui.windows.gui_preview import floating_preview_top_left

        self.assertEqual(floating_preview_top_left(1000, 660, 100, 80, 1600, 900), (400, 200))
        self.assertEqual(floating_preview_top_left(2000, 1200, 0, 0, 800, 600), (0, 0))

    def test_floating_preview_size_fills_the_screen(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from PySide6.QtCore import QRect

        from ui.windows.gui_preview import floating_preview_size_for

        screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
        with patch("ui.windows.gui_preview.QGuiApplication.primaryScreen", return_value=screen):
            width, height = floating_preview_size_for(None)
        self.assertEqual(width, 1912)
        self.assertEqual(height, 1072)

    def test_clamp_seek_ms(self):
        from ui.playback.preview_keyboard import clamp_seek_ms

        self.assertEqual(clamp_seek_ms(5000, -3000), 2000)
        self.assertEqual(clamp_seek_ms(1000, -3000), 0)
        self.assertEqual(clamp_seek_ms(8000, 3000, total_ms=10000), 10000)
        self.assertEqual(clamp_seek_ms(8000, 3000, total_ms=0), 11000)

    def test_resolve_seek_base_prefers_pending(self):
        from ui.playback.preview_keyboard import resolve_seek_base_ms

        self.assertEqual(resolve_seek_base_ms(5000, None), 5000)
        self.assertEqual(resolve_seek_base_ms(5000, 8000), 8000)

    def test_resolve_display_time_keeps_pending_inflight(self):
        from ui.playback.preview_keyboard import resolve_display_time_ms

        display, pending = resolve_display_time_ms(5000, 8000)
        self.assertEqual(display, 8000)
        self.assertEqual(pending, 8000)

        display, pending = resolve_display_time_ms(7900, 8000)
        self.assertEqual(display, 7900)
        self.assertIsNone(pending)

    def test_resolve_display_time_keeps_backward_seek(self):
        from ui.playback.preview_keyboard import resolve_display_time_ms

        # Clock is still on the later frame. Dropping the target here makes the
        # next nudge seek forward again, so the picture bounces.
        display, pending = resolve_display_time_ms(10000, 7000)
        self.assertEqual(display, 7000)
        self.assertEqual(pending, 7000)

        display, pending = resolve_display_time_ms(0, 7000)
        self.assertEqual(display, 7000)
        self.assertEqual(pending, 7000)

        display, pending = resolve_display_time_ms(7200, 7000)
        self.assertEqual(display, 7200)
        self.assertIsNone(pending)

    def test_focus_blocks_preview_keys_for_editors(self):
        from PySide6.QtWidgets import QLineEdit, QPushButton, QWidget

        from ui.playback.preview_keyboard import focus_blocks_preview_keys

        edit = QLineEdit()
        self.addCleanup(edit.deleteLater)
        self.assertTrue(focus_blocks_preview_keys(edit))

        button = QPushButton("Preview")
        self.addCleanup(button.deleteLater)
        self.assertFalse(focus_blocks_preview_keys(button))

        host = QWidget()
        self.addCleanup(host.deleteLater)
        host.setProperty("previewKeyboardPassthrough", True)
        self.assertTrue(focus_blocks_preview_keys(host))

    def test_transport_filter_toggles_and_seeks(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QWidget

        from ui.playback.preview_keyboard import PreviewTransportKeyFilter

        host = QWidget()
        host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        host.show()
        host.activateWindow()
        self.addCleanup(host.close)
        self.addCleanup(host.deleteLater)

        toggles = []
        seeks = []

        filt = PreviewTransportKeyFilter(
            host,
            is_active=lambda: True,
            on_toggle=lambda: toggles.append(1),
            on_seek=lambda delta: seeks.append(delta),
            seek_step_ms=3000,
            hold_seek_step_ms=500,
            hold_tick_ms=100,
            parent=host,
        )

        space = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(filt.eventFilter(host, space))
        self.assertEqual(toggles, [1])

        r_key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_R, Qt.KeyboardModifier.NoModifier)
        self.assertFalse(filt.eventFilter(host, r_key))

        replays = []
        filt._on_replay = lambda: replays.append(1)
        self.assertTrue(filt.eventFilter(host, r_key))
        self.assertEqual(replays, [1])

        left = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
        right = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(filt.eventFilter(host, left))
        self.assertTrue(filt.eventFilter(host, right))
        self.assertEqual(seeks, [-3000, 3000])

        # OS auto-repeat must not stack another coarse jump.
        repeat = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Right,
            Qt.KeyboardModifier.NoModifier,
            "",
            True,
            1,
        )
        self.assertTrue(filt.eventFilter(host, repeat))
        self.assertEqual(seeks, [-3000, 3000])

        filt._on_hold_tick()
        self.assertEqual(seeks, [-3000, 3000, 500])

        release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(filt.eventFilter(host, release))
        self.assertEqual(filt._held_dir, 0)

    def test_transport_filter_inactive_passes_through(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QWidget

        from ui.playback.preview_keyboard import PreviewTransportKeyFilter

        host = QWidget()
        self.addCleanup(host.deleteLater)
        filt = PreviewTransportKeyFilter(
            host,
            is_active=lambda: False,
            on_toggle=MagicMock(),
            on_seek=MagicMock(),
            parent=host,
        )
        space = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        self.assertFalse(filt.eventFilter(host, space))

    def test_escape_on_embedded_preview_returns_to_results(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QWidget

        from ui.playback.preview_keyboard import PreviewTransportKeyFilter

        host = QWidget()
        host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        left = []
        host._on_embedded_escape = lambda: left.append(1)
        host.show()
        host.activateWindow()
        self.addCleanup(host.close)
        self.addCleanup(host.deleteLater)

        filt = PreviewTransportKeyFilter(
            host,
            is_active=lambda: False,
            on_toggle=MagicMock(),
            on_seek=MagicMock(),
            parent=host,
        )
        esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(filt.eventFilter(host, esc))
        self.assertEqual(left, [1])

    def test_escape_without_embedded_preview_is_ignored(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QWidget

        from ui.playback.preview_keyboard import PreviewTransportKeyFilter

        host = QWidget()
        self.addCleanup(host.deleteLater)
        filt = PreviewTransportKeyFilter(
            host,
            is_active=lambda: True,
            on_toggle=MagicMock(),
            on_seek=MagicMock(),
            parent=host,
        )
        esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        self.assertFalse(filt.eventFilter(host, esc))


class ExpandedPreviewNudgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            cls._app = QApplication([])

    def test_nudge_seek_preserves_paused_state(self):
        from ui.playback.expanded_preview_chrome import ExpandedPreviewChrome

        chrome = ExpandedPreviewChrome()
        self.addCleanup(chrome.deleteLater)
        chrome.video_path = "D:/clip.mp4"
        player = MagicMock()
        player.is_available.return_value = True
        player.get_time.return_value = 5000
        player.get_length.return_value = 20000
        player.is_playing.return_value = False
        player.has_locked_window.return_value = False
        chrome.player = player
        chrome._playback_ready = True

        chrome._nudge_seek(3000)

        player.set_time.assert_called_with(8000, unlock=True)
        player.resume.assert_not_called()

    def test_nudge_seek_accumulates_from_pending(self):
        from ui.playback.expanded_preview_chrome import ExpandedPreviewChrome

        chrome = ExpandedPreviewChrome()
        self.addCleanup(chrome.deleteLater)
        chrome.video_path = "D:/clip.mp4"
        player = MagicMock()
        player.is_available.return_value = True
        player.get_time.return_value = 5000  # VLC still at old clock
        player.get_length.return_value = 60000
        player.is_playing.return_value = True
        player.has_locked_window.return_value = False
        chrome.player = player
        chrome._playback_ready = True
        chrome._pending_ui_seek_ms = 8000

        chrome._nudge_seek(500)

        player.set_time.assert_called_with(8500, unlock=True)
        player.resume.assert_not_called()

    def test_nudge_while_playing_does_not_resume(self):
        from ui.playback.expanded_preview_chrome import ExpandedPreviewChrome

        chrome = ExpandedPreviewChrome()
        self.addCleanup(chrome.deleteLater)
        chrome.video_path = "D:/clip.mp4"
        player = MagicMock()
        player.is_available.return_value = True
        player.get_time.return_value = 12000
        player.get_length.return_value = 60000
        player.is_playing.return_value = True
        player.has_locked_window.return_value = False
        chrome.player = player
        chrome._playback_ready = True

        chrome._nudge_seek(3000)
        chrome._nudge_seek(3000)

        self.assertEqual(player.set_time.call_count, 2)
        player.resume.assert_not_called()
        self.assertEqual(player.set_time.call_args_list[0].args[0], 15000)
        self.assertEqual(player.set_time.call_args_list[1].args[0], 18000)

    def test_space_at_clip_end_continues_instead_of_replaying(self):
        from ui.playback.expanded_preview_chrome import ExpandedPreviewChrome

        chrome = ExpandedPreviewChrome()
        self.addCleanup(chrome.deleteLater)
        chrome.apply_texts(
            {
                "preview_dialog_play": "Play",
                "preview_dialog_pause": "Pause",
                "preview_dialog_continue": "Continue",
                "preview_dialog_replay": "Replay",
            }
        )
        chrome.video_path = "D:/clip.mp4"
        chrome.start_sec = 10.0
        chrome.end_sec = 16.0
        player = MagicMock()
        player.is_available.return_value = True
        player.is_playing.return_value = False
        player.has_locked_window.return_value = True
        player.get_time.return_value = 16000
        player._loaded_video_path = "D:/clip.mp4"

        def _unlock():
            player.has_locked_window.return_value = False
            player.is_playing.return_value = True

        player.unlock_full_playback.side_effect = _unlock
        chrome.player = player

        chrome._toggle_play()

        player.play.assert_not_called()
        player.unlock_full_playback.assert_called_once()
        player.resume.assert_called()
        self.assertEqual(chrome.play_button.glyph(), "pause")

    def test_replay_restarts_the_hit_window(self):
        from ui.playback.expanded_preview_chrome import ExpandedPreviewChrome

        chrome = ExpandedPreviewChrome()
        self.addCleanup(chrome.deleteLater)
        chrome.video_path = "D:/clip.mp4"
        chrome.start_sec = 10.0
        chrome.end_sec = 16.0
        player = MagicMock()
        player.is_available.return_value = True
        player.is_playing.return_value = True
        player.has_locked_window.return_value = True
        player.get_time.return_value = 16000
        player._loaded_video_path = "D:/clip.mp4"
        player.play.return_value = True
        chrome.player = player

        chrome._replay_clip()

        player.play.assert_called_once_with("D:/clip.mp4", 10.0, stop_sec=16.0)


class PreviewGlyphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            cls._app = QApplication([])

    def test_clear_glyph_is_a_broom_not_an_x(self):
        from ui.playback.preview_glyphs import PreviewGlyphButton

        button = PreviewGlyphButton("clear")
        self.addCleanup(button.deleteLater)
        pix = button.grab()
        self.assertGreater(pix.width(), 8)
        self.assertEqual(button.glyph(), "clear")

    def test_preview_icons_use_pill_chrome_and_active_tone(self):
        from ui.playback.preview_glyphs import PreviewGlyphButton

        play = PreviewGlyphButton("play")
        replay = PreviewGlyphButton("replay")
        fullscreen = PreviewGlyphButton("fullscreen")
        for button in (play, replay, fullscreen):
            self.addCleanup(button.deleteLater)
            self.assertEqual(button.property("chrome"), "previewIcon")
            self.assertEqual(button.property("active"), "false")
        play.set_glyph("pause")
        self.assertEqual(play.property("active"), "true")
        fullscreen.set_glyph("exit_fullscreen")
        self.assertEqual(fullscreen.property("active"), "true")
        play.set_glyph("play")
        self.assertEqual(play.property("active"), "false")


class TimecodeDisplayTests(unittest.TestCase):
    def test_preview_and_result_clocks_roll_into_hours(self):
        from ui.playback.expanded_preview_chrome import _format_ms
        from ui.views.table_views import _format_time_range, _format_time_value

        self.assertEqual(_format_ms(65_000), "01:05")
        self.assertEqual(_format_ms(3_665_000), "1:01:05")
        self.assertEqual(_format_time_value(3665), "1:01:05")
        self.assertEqual(_format_time_range(3665, 3725, {}), "1:01:05-1:02:05")
        self.assertEqual(_format_time_range(12, 18, {}), "00:12-00:18")


if __name__ == "__main__":
    unittest.main()
