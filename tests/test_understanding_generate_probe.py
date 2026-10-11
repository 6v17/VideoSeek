"""Generate/batch must not probe the remote VLM on the UI thread."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ui.widgets.understanding_services_panel import UnderstandingServicesPanel
from ui.windows.gui_understanding import UnderstandingGuiMixin


class _GenerateHost(UnderstandingGuiMixin):
    def __init__(self):
        self.texts = {
            "feature_understanding": "Understanding",
            "understanding_generation_failed": "Failed",
            "understanding_not_ready": "Not ready",
            "warning_title": "Warning",
            "understanding_video_select_hint": "Pick a video",
            "understanding_video_no_chunks": "No chunks",
        }
        self.indexing_controller = MagicMock()
        self.indexing_controller.is_running.return_value = False
        self.understanding_controller = MagicMock()
        self.understanding_controller.is_running.return_value = False
        self.understanding_page = MagicMock()
        self.understanding_page.chunk_timeline.segment_count.return_value = 0
        self._fetch_calls = []

    def _ensure_startup_migration_idle(self, _feature):
        return True

    def _fetch_understanding_resource_status(self, *, probe_remote=False, install_bootstrap=False, use_cache=True):
        self._fetch_calls.append(
            {"probe_remote": probe_remote, "install_bootstrap": install_bootstrap, "use_cache": use_cache}
        )
        return {"understanding_ready": True}

    def _refresh_understanding_ui(self, status=None, *, probe_remote: bool = False):
        return None

    def show_info_dialog(self, *_args, **_kwargs):
        return None

    def show_error_dialog(self, *_args, **_kwargs):
        return None

    def _selected_understanding_video_id(self):
        return ""


class UnderstandingGenerateProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_generate_uses_local_status_without_remote_probe(self):
        host = _GenerateHost()
        with patch("ui.windows.gui_understanding.get_understanding_resource_status") as probe:
            host.start_generate_understanding_evidence()
            probe.assert_not_called()
        self.assertEqual(len(host._fetch_calls), 1)
        self.assertEqual(host._fetch_calls[0]["probe_remote"], False)
        self.assertEqual(host._fetch_calls[0]["install_bootstrap"], False)

    def test_batch_uses_local_status_without_remote_probe(self):
        host = _GenerateHost()
        with patch("ui.windows.gui_understanding.get_understanding_resource_status") as probe:
            host.start_generate_understanding_batch()
            probe.assert_not_called()
        self.assertEqual(len(host._fetch_calls), 1)
        self.assertEqual(host._fetch_calls[0]["probe_remote"], False)

    def test_service_test_routes_by_nav_tab(self):
        panel = UnderstandingServicesPanel()
        host = _GenerateHost()
        host.understanding_services_dialog = panel
        host.test_understanding_vlm_connection = MagicMock()
        host.test_understanding_llm_connection = MagicMock()
        host.test_understanding_asr_connection = MagicMock()

        for row in range(panel.nav.count()):
            item = panel.nav.item(row)
            if item is not None and str(item.data(Qt.ItemDataRole.UserRole) or "") == "asr":
                panel.nav.setCurrentRow(row)
                break
        self.assertEqual(panel.current_nav_id(), "asr")
        host.test_understanding_service_connection()
        host.test_understanding_asr_connection.assert_called_once()
        host.test_understanding_vlm_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
