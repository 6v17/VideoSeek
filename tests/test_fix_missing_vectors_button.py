import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QPushButton

from ui.windows.gui_library_indexing import LibraryIndexingGuiMixin


class FixMissingVectorsButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def _host(self, button, *, busy=False):
        host = LibraryIndexingGuiMixin.__new__(LibraryIndexingGuiMixin)
        host.texts = {
            "fix_missing_vectors": "修复向量",
            "fix_missing_vectors_count": "修复 {count}",
            "fix_missing_vectors_hint": "hint",
        }
        host.library_page = SimpleNamespace(btn_fix_missing_vectors=button)
        host.indexing_controller = SimpleNamespace(is_busy=lambda: busy)
        host._dialogue_index_running = lambda: False
        host._remove_library_worker_running = lambda: False
        host._remove_selected_videos_worker_running = lambda: False
        return host

    @patch("src.services.team_mode_service.is_team_client_mode", return_value=False)
    def test_warning_color_when_vectors_can_be_repaired(self, _team):
        button = QPushButton("修复向量")
        button.setObjectName("GhostButton")
        host = self._host(button)
        divider = QPushButton()
        divider.setVisible(False)
        host.library_page.visual_repair_divider = divider
        host.library_page.btn_index_issues = QPushButton()
        host.library_page.btn_index_issues.setVisible(False)
        host.library_page.btn_cleanup_missing = QPushButton()
        host.library_page.btn_cleanup_missing.setVisible(False)

        host._refresh_fix_missing_vectors_button(count=3)

        self.assertEqual(button.objectName(), "WarningButton")
        self.assertTrue(button.isEnabled())
        self.assertFalse(button.isHidden())
        self.assertFalse(divider.isHidden())
        self.assertEqual(button.text(), "修复 3")

    @patch("src.services.team_mode_service.is_team_client_mode", return_value=False)
    def test_ghost_color_when_nothing_to_repair(self, _team):
        button = QPushButton("修复 3")
        button.setObjectName("WarningButton")
        host = self._host(button)
        divider = QPushButton()
        host.library_page.visual_repair_divider = divider
        host.library_page.btn_index_issues = QPushButton()
        host.library_page.btn_index_issues.setVisible(False)
        host.library_page.btn_cleanup_missing = QPushButton()
        host.library_page.btn_cleanup_missing.setVisible(False)

        host._refresh_fix_missing_vectors_button(count=0)

        self.assertEqual(button.objectName(), "GhostButton")
        self.assertFalse(button.isEnabled())
        self.assertTrue(button.isHidden())
        self.assertTrue(divider.isHidden())
        self.assertEqual(button.text(), "修复向量")
