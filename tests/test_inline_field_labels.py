"""Inline search-field labels must not be clipped by a hard-coded width."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")

from PySide6.QtWidgets import QApplication, QLabel

from ui.widgets.search_panel import SearchPanel


class InlineFieldLabelLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_english_inline_labels_fit_without_fixed_clip(self):
        panel = SearchPanel()
        samples = {
            "search_scope_label": "Search scope",
            "image_search_mode_label": "Image mode",
            "search_mode_label": "Search mode",
            "mobile_toggle_label": "Phone",
            "dialogue_search_mode_label": "Match mode",
            "text_search_enhance_label": "Enhance",
        }
        for attr, text in samples.items():
            getattr(panel, attr).setText(text)
        panel.relayout_inline_fields()

        for attr, text in samples.items():
            label: QLabel = getattr(panel, attr)
            self.assertEqual(label.objectName(), "InlineFieldLabel")
            # Must not be locked to the old 60px hard width.
            self.assertNotEqual(label.maximumWidth(), 60)
            needed = label.fontMetrics().horizontalAdvance(text)
            self.assertGreaterEqual(
                label.minimumWidth(),
                needed,
                f"{attr} minWidth {label.minimumWidth()} < text {needed}px for {text!r}",
            )
            # After layout, width should fit the text (allow 1px rounding).
            label.adjustSize()
            self.assertGreaterEqual(
                max(label.width(), label.minimumWidth()) + 1,
                needed,
                f"{attr} clipped: width={label.width()} text={needed} for {text!r}",
            )


if __name__ == "__main__":
    unittest.main()
