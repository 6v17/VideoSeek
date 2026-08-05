"""Tests for detachable search results floating window."""

from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ui.widgets.results_float_window import ResultsFloatWindow


def _ensure_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class ResultsFloatWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _ensure_app()

    def test_take_and_release_card_preserves_widget(self):
        host = ResultsFloatWindow()
        card = QWidget()
        label = QLabel("results", card)
        layout = QVBoxLayout(card)
        layout.addWidget(label)

        host.take_card(card)
        self.assertTrue(host.is_hosting())
        self.assertIs(card.parent(), host.host)

        released = host.release_card()
        self.assertIs(released, card)
        self.assertFalse(host.is_hosting())
        self.assertIsNone(card.parent())
        # Child widgets survive reparent cycles.
        self.assertEqual(label.text(), "results")

    def test_close_requests_dock_while_hosting(self):
        host = ResultsFloatWindow()
        card = QWidget()
        host.take_card(card)
        seen = []
        host.dock_requested.connect(lambda: seen.append(True))

        host.close()

        self.assertEqual(seen, [True])
        # Card still hosted until owner docks it.
        self.assertTrue(host.is_hosting())


if __name__ == "__main__":
    unittest.main()
