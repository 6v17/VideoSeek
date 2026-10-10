"""Quit-time QThread shutdown without destroying a live thread."""

from __future__ import annotations

import unittest

from ui import threading_utils


class _FakeThread:
    def __init__(self, *, finish_on_wait: bool = False):
        self.finish_on_wait = finish_on_wait
        self.running = True
        self.terminated = False
        self.blocked = False

    def isRunning(self):
        return self.running

    def blockSignals(self, blocked):
        self.blocked = bool(blocked)

    def requestInterruption(self):
        return None

    def quit(self):
        return None

    def wait(self, _wait_ms):
        if self.finish_on_wait:
            self.running = False
            return True
        return False

    def terminate(self):
        self.terminated = True


class ShutdownThreadTests(unittest.TestCase):
    def setUp(self):
        threading_utils._PARKED_THREADS.clear()

    def tearDown(self):
        threading_utils._PARKED_THREADS.clear()

    def test_running_thread_is_parked_instead_of_terminated(self):
        thread = _FakeThread()
        threading_utils.shutdown_thread(thread, wait_ms=10)
        self.assertFalse(thread.terminated)
        self.assertTrue(thread.blocked)
        self.assertIn(thread, threading_utils.parked_threads())

    def test_allow_terminate_still_kills_a_stuck_thread(self):
        thread = _FakeThread()
        threading_utils.shutdown_thread(thread, allow_terminate=True, wait_ms=10)
        self.assertTrue(thread.terminated)

    def test_finished_thread_is_not_parked(self):
        thread = _FakeThread(finish_on_wait=True)
        threading_utils.shutdown_thread(thread, wait_ms=10)
        self.assertFalse(thread.terminated)
        self.assertEqual(threading_utils.parked_threads(), [])
