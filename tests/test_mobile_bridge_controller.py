"""MobileBridgeController unit tests — kept out of test_z_qt_controllers.

VLC/preview tests later in the suite have corrupted native heaps on Windows CI
(0xc0000374); creating QObject+MagicMock parents afterward then crashes during
GC. These tests run earlier (filename order) on a clean process state.
"""

from __future__ import annotations

import os
import types
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")


def setUpModule():
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        QApplication([])


def _parent():
    return types.SimpleNamespace()


class MobileBridgeControllerTests(unittest.TestCase):
    @patch("src.web.mobile_bridge.MobileBridgeService")
    def test_start_creates_service_once_and_returns_access_url(self, mock_service_cls):
        from ui.controllers.mobile_bridge_controller import MobileBridgeController

        parent = _parent()
        service = MagicMock()
        service.is_running.side_effect = [False, True]
        service.get_access_url.return_value = "http://192.168.1.2:8918/?token=abc"
        mock_service_cls.return_value = service
        controller = MobileBridgeController(parent)
        statuses = []
        controller.status_changed.connect(statuses.append)

        url = controller.start()

        mock_service_cls.assert_called_once()
        kwargs = mock_service_cls.call_args.kwargs
        self.assertTrue(callable(kwargs["on_search_requested"]))
        service.start.assert_called_once()
        self.assertEqual(url, "http://192.168.1.2:8918/?token=abc")
        self.assertEqual(statuses, ["running"])

    @patch("src.web.mobile_bridge.MobileBridgeService")
    def test_start_reuses_running_service_without_restarting(self, mock_service_cls):
        from ui.controllers.mobile_bridge_controller import MobileBridgeController

        parent = _parent()
        service = MagicMock()
        service.is_running.return_value = True
        service.get_access_url.return_value = "http://192.168.1.2:8918/?token=abc"
        mock_service_cls.return_value = service
        controller = MobileBridgeController(parent)
        statuses = []
        controller.status_changed.connect(statuses.append)

        first_url = controller.start()
        second_url = controller.start()

        self.assertEqual(first_url, "http://192.168.1.2:8918/?token=abc")
        self.assertEqual(second_url, "http://192.168.1.2:8918/?token=abc")
        service.start.assert_not_called()
        self.assertEqual(statuses, [])

    def test_handle_search_requested_requires_ui_accept(self):
        from ui.controllers.mobile_bridge_controller import MobileBridgeController

        parent = _parent()
        accepted = []

        def _accept(payload):
            accepted.append(dict(payload))
            return {"ok": True}

        parent.accept_mobile_search_request = _accept
        controller = MobileBridgeController(parent)

        payload = {
            "search_kind": "compose",
            "query": "night rain",
            "image_path": "D:/Migrated/data/mobile_uploads/query.png",
            "source": "192.168.1.10",
        }
        result = controller._handle_search_requested(payload)

        self.assertEqual(accepted, [payload])
        self.assertTrue(result.get("ok"))

    def test_handle_search_requested_raises_when_ui_rejects(self):
        from ui.controllers.mobile_bridge_controller import MobileBridgeController

        parent = _parent()
        parent.accept_mobile_search_request = lambda _payload: {
            "ok": False,
            "error": "search_not_ready",
        }
        controller = MobileBridgeController(parent)
        with self.assertRaises(RuntimeError):
            controller._handle_search_requested({"search_kind": "image"})


if __name__ == "__main__":
    unittest.main()
