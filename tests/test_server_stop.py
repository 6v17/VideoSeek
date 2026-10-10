"""UI-thread server stop must not join the server thread inline."""

from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.web.server_stop import release_server_thread
from ui.controllers.team_mode_controller import TeamModeController


class ReleaseServerThreadTests(unittest.TestCase):
    def test_wait_joins_on_the_caller(self):
        thread = MagicMock()
        self.assertIsNone(release_server_thread(thread, wait=True, timeout=1.5))
        thread.join.assert_called_once_with(timeout=1.5)

    def test_background_join_is_not_the_caller(self):
        thread = MagicMock()
        seen = []

        def _join(**_kwargs):
            seen.append(threading.current_thread().name)

        thread.join.side_effect = _join
        waiter = release_server_thread(thread, wait=False, timeout=1.0)
        self.assertIsNotNone(waiter)
        waiter.join(timeout=2.0)
        self.assertEqual(seen, ["ServerStop"])


class TeamStopServerTests(unittest.TestCase):
    def _host(self):
        return SimpleNamespace(
            _api_service=MagicMock(),
            parent_window=SimpleNamespace(agent_api_controller=None),
            _emit_progress=lambda *_args, **_kwargs: None,
            refresh_status=lambda: {},
        )

    @patch("ui.controllers.team_mode_controller.stop_team_server_media")
    @patch("ui.controllers.team_mode_controller.threading.Thread")
    def test_ui_thread_stops_nginx_in_the_background(self, thread_cls, stop_media):
        host = self._host()
        service = host._api_service
        TeamModeController.stop_server(host)
        stop_media.assert_not_called()
        thread_cls.assert_called_once()
        self.assertEqual(thread_cls.call_args.kwargs["name"], "TeamMediaStop")
        service.stop.assert_called_once_with()

    @patch("ui.controllers.team_mode_controller.threading.current_thread")
    @patch("ui.controllers.team_mode_controller.threading.main_thread")
    @patch("ui.controllers.team_mode_controller.stop_team_server_media")
    def test_worker_thread_stops_nginx_inline(self, stop_media, main_thread, current_thread):
        main_thread.return_value = MagicMock()
        current_thread.return_value = MagicMock()
        host = self._host()
        TeamModeController.stop_server(host)
        stop_media.assert_called_once_with()
