"""Preferred team ports stay at defaults; session remaps do not stick in config."""

from __future__ import annotations

import unittest
from unittest import mock

from src.app.config import DEFAULT_CONFIG
from src.services.team_mode_service import (
    build_team_server_status,
    clear_active_team_ports,
    get_preferred_team_ports,
    set_active_team_ports,
)


class TeamPreferredPortsTests(unittest.TestCase):
    def tearDown(self):
        clear_active_team_ports()

    def test_preferred_ports_match_defaults(self):
        api, media = get_preferred_team_ports()
        self.assertEqual(api, int(DEFAULT_CONFIG["team_api_port"]))
        self.assertEqual(media, int(DEFAULT_CONFIG["team_nginx_port"]))
        self.assertEqual(api, 8765)
        self.assertEqual(media, 18080)

    def test_status_uses_session_ports_when_active(self):
        set_active_team_ports(api_port=8767, nginx_port=18081)
        with mock.patch("src.services.team_mode_service.detect_lan_ip", return_value="192.168.1.8"):
            with mock.patch("src.services.team_mode_service.load_config", return_value={}):
                with mock.patch("src.services.team_mode_service.is_nginx_running", return_value=False):
                    with mock.patch("src.services.team_mode_service.nginx_bundle_ready", return_value=True):
                        status = build_team_server_status({})
        self.assertEqual(status["api_port"], 8767)
        self.assertEqual(status["nginx_port"], 18081)
        self.assertEqual(status["api_base_url"], "http://192.168.1.8:8767")
        self.assertEqual(status["media_base_url"], "http://192.168.1.8:18081")

    def test_status_falls_back_to_preferred_when_idle(self):
        clear_active_team_ports()
        with mock.patch("src.services.team_mode_service.detect_lan_ip", return_value="10.0.0.2"):
            with mock.patch("src.services.team_mode_service.load_config", return_value={"team_api_port": 9999}):
                with mock.patch("src.services.team_mode_service.is_nginx_running", return_value=False):
                    with mock.patch("src.services.team_mode_service.nginx_bundle_ready", return_value=True):
                        status = build_team_server_status({"team_api_port": 9999})
        self.assertEqual(status["api_port"], 8765)
        self.assertEqual(status["nginx_port"], 18080)


if __name__ == "__main__":
    unittest.main()
