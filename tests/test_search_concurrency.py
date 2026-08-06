"""Tests for Agent API search concurrency slot acquire / busy fail-fast."""

from __future__ import annotations

import threading
import unittest

from src.web.agent_api.constants import (
    SearchEngineBusyError,
    acquire_search_slot,
    configure_search_concurrency,
    get_max_concurrent_searches,
    get_search_queue_wait_sec,
)


class SearchConcurrencyTests(unittest.TestCase):
    def tearDown(self):
        configure_search_concurrency(
            {
                "agent_api_max_concurrent_searches": 10,
                "agent_api_search_queue_wait_sec": 12,
            }
        )

    def test_configure_search_concurrency_from_config(self):
        configure_search_concurrency(
            {
                "agent_api_max_concurrent_searches": 3,
                "agent_api_search_queue_wait_sec": 5,
            }
        )
        self.assertEqual(get_max_concurrent_searches(), 3)
        self.assertEqual(get_search_queue_wait_sec(), 5.0)

    def test_acquire_search_slot_succeeds_when_capacity(self):
        configure_search_concurrency(
            {
                "agent_api_max_concurrent_searches": 2,
                "agent_api_search_queue_wait_sec": 1,
            }
        )
        with acquire_search_slot(timeout=0.5):
            pass

    def test_acquire_search_slot_busy_when_full(self):
        configure_search_concurrency(
            {
                "agent_api_max_concurrent_searches": 1,
                "agent_api_search_queue_wait_sec": 0,
            }
        )
        hold = threading.Event()
        released = threading.Event()

        def _holder():
            with acquire_search_slot(timeout=1.0):
                hold.set()
                released.wait(timeout=2.0)

        thread = threading.Thread(target=_holder, daemon=True)
        thread.start()
        self.assertTrue(hold.wait(timeout=1.0))
        with self.assertRaises(SearchEngineBusyError):
            with acquire_search_slot(timeout=0.05):
                pass
        released.set()
        thread.join(timeout=2.0)

    def test_team_client_maps_engine_busy_http(self):
        from src.services.team_client_search import TeamSearchBusyError, is_team_search_busy_error, _raise_from_http_error

        class FakeHTTPError(Exception):
            def __init__(self):
                self.code = 503
                self.reason = "Service Unavailable"

            def read(self):
                return b'{"ok":false,"error":{"code":"engine_busy","message":"Search engine is busy."}}'

        with self.assertRaises(TeamSearchBusyError) as ctx:
            _raise_from_http_error(FakeHTTPError())  # type: ignore[arg-type]
        self.assertTrue(is_team_search_busy_error(str(ctx.exception)))


if __name__ == "__main__":
    unittest.main()
