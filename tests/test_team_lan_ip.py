"""Tests for LAN IP selection used by team mode."""

from __future__ import annotations

import unittest

from src.services.team_paths import (
    is_unusable_lan_ip,
    lan_ip_preference_score,
    pick_lan_ip,
)


class TeamLanIpTests(unittest.TestCase):
    def test_rejects_clash_fake_ip_range(self):
        self.assertTrue(is_unusable_lan_ip("198.18.0.1"))
        self.assertTrue(is_unusable_lan_ip("198.19.255.10"))
        self.assertTrue(is_unusable_lan_ip("127.0.0.1"))
        self.assertTrue(is_unusable_lan_ip("169.254.1.2"))
        self.assertFalse(is_unusable_lan_ip("192.168.1.8"))

    def test_prefers_office_lan_over_vpn_fake_and_public(self):
        chosen = pick_lan_ip(["198.18.0.1", "8.8.8.8", "192.168.1.23", "10.0.0.5"])
        self.assertEqual(chosen, "192.168.1.23")
        self.assertLess(lan_ip_preference_score("192.168.1.23"), lan_ip_preference_score("10.0.0.5"))

    def test_falls_back_when_only_fake_ips(self):
        self.assertEqual(pick_lan_ip(["198.18.0.1", "127.0.0.1"]), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
