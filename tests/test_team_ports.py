"""Tests for team TCP port allocation."""

from __future__ import annotations

import socket
import unittest

from src.services.team_paths import find_available_tcp_port, tcp_port_is_available


class TeamPortAllocationTests(unittest.TestCase):
    def test_preferred_port_when_free(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            preferred = int(probe.getsockname()[1])
        # Preferred just released; should usually be free again.
        chosen = find_available_tcp_port(preferred, host="127.0.0.1", attempts=5)
        self.assertGreaterEqual(chosen, preferred)
        self.assertTrue(tcp_port_is_available(chosen, host="127.0.0.1"))

    def test_skips_occupied_preferred(self):
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        preferred = int(holder.getsockname()[1])
        try:
            chosen = find_available_tcp_port(preferred, host="127.0.0.1", attempts=10)
            self.assertNotEqual(chosen, preferred)
            self.assertGreater(chosen, preferred)
        finally:
            holder.close()


if __name__ == "__main__":
    unittest.main()
