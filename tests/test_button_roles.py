"""Main-window QPushButtons must use the shared action roles."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QAbstractButton, QApplication, QCheckBox, QPushButton, QToolButton

from ui.widgets.button_roles import ACTION_ROLES
from ui.widgets.components import LibraryPage, LinkSearchPage, NavigationSidebar, SearchPage
from ui.widgets.settings.page import SettingsPage
from ui.widgets.understanding_page import UnderstandingEvidencePage
from ui.windows.gui_settings import SettingsGuiMixin


class _DirtyHost:
    def __init__(self):
        self.settings_page = SettingsPage()
        self._settings_dirty = False


class ButtonRoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_save_stays_primary_when_clean(self):
        host = _DirtyHost()
        SettingsGuiMixin._set_settings_dirty(host, False)
        self.assertEqual(host.settings_page.btn_save.objectName(), "PrimaryButton")
        self.assertFalse(host.settings_page.btn_save.isEnabled())
        SettingsGuiMixin._set_settings_dirty(host, True)
        self.assertEqual(host.settings_page.btn_save.objectName(), "PrimaryButton")
        self.assertTrue(host.settings_page.btn_save.isEnabled())

    def test_main_pages_push_buttons_use_action_roles(self):
        roots = (
            NavigationSidebar(),
            SearchPage(),
            LibraryPage(),
            LinkSearchPage(),
            UnderstandingEvidencePage(),
            SettingsPage(),
        )
        outside = []
        for root in roots:
            for button in root.findChildren(QPushButton):
                name = button.objectName() or "(empty)"
                if name not in ACTION_ROLES:
                    outside.append((type(root).__name__, name, button.text()[:40]))
        self.assertEqual(outside, [], msg=f"non-role QPushButtons: {outside}")

    def test_main_pages_tool_and_corner_buttons_are_named(self):
        roots = (
            NavigationSidebar(),
            SearchPage(),
            LibraryPage(),
            LinkSearchPage(),
            UnderstandingEvidencePage(),
            SettingsPage(),
        )
        unnamed = []
        for root in roots:
            for button in root.findChildren(QToolButton):
                if not str(button.objectName() or "").strip():
                    unnamed.append((type(root).__name__, "QToolButton"))
            for button in root.findChildren(QAbstractButton):
                if isinstance(button, (QPushButton, QToolButton, QCheckBox)):
                    continue
                if not str(button.objectName() or "").strip():
                    unnamed.append((type(root).__name__, type(button).__name__))
        self.assertEqual(unnamed, [], msg=f"unnamed chrome buttons: {unnamed}")


if __name__ == "__main__":
    unittest.main()
