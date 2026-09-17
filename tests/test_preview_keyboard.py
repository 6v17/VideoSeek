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


if __name__ == "__main__":
    unittest.main()
