import os
import unittest
from unittest.mock import patch


class TeamModeBindHostTests(unittest.TestCase):
    def test_resolve_api_bind_host_prefers_lan_ip(self):
        from ui.controllers.team_mode_controller import TeamModeController

        controller = TeamModeController(None)
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("VIDEOSEEK_AGENT_API_HOST", None)
            with patch(
                "ui.controllers.team_mode_controller.detect_lan_ip",
                return_value="192.168.0.42",
            ):
                self.assertEqual(controller._resolve_api_bind_host(), "192.168.0.42")

    def test_resolve_api_bind_host_env_override(self):
        from ui.controllers.team_mode_controller import TeamModeController

        controller = TeamModeController(None)
        with patch.dict("os.environ", {"VIDEOSEEK_AGENT_API_HOST": "0.0.0.0"}):
            self.assertEqual(controller._resolve_api_bind_host(), "0.0.0.0")


if __name__ == "__main__":
    unittest.main()
