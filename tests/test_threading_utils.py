"""Quit-time QThread shutdown without destroying a live thread."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

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


class _Owner:
    def __init__(self):
        self.worker = None


class ReleaseFinishedThreadTests(unittest.TestCase):
    def setUp(self):
        threading_utils._PARKED_THREADS.clear()

    def tearDown(self):
        threading_utils._PARKED_THREADS.clear()

    def test_stopped_thread_is_cleared_and_deleted(self):
        owner = _Owner()
        thread = MagicMock()
        thread.isRunning.return_value = False
        owner.worker = thread

        threading_utils.release_finished_thread(owner, "worker", thread)

        self.assertIsNone(owner.worker)
        thread.deleteLater.assert_called_once()

    def test_older_thread_release_keeps_the_current_one(self):
        owner = _Owner()
        old = MagicMock()
        old.isRunning.return_value = False
        current = MagicMock()
        owner.worker = current

        threading_utils.release_finished_thread(owner, "worker", old)

        self.assertIs(owner.worker, current)
        old.deleteLater.assert_called_once()
        current.deleteLater.assert_not_called()

    def test_running_thread_is_cleared_but_not_deleted(self):
        owner = _Owner()
        thread = _FakeThread()
        owner.worker = thread

        threading_utils.release_finished_thread(owner, "worker", thread)

        self.assertIsNone(owner.worker)
        self.assertIn(thread, threading_utils.parked_threads())
        self.assertFalse(hasattr(thread, "deleteLater"))


class ConnectOnReceiverTests(unittest.TestCase):
    def test_same_thread_emit_reaches_the_receiver_slot(self):
        from PySide6.QtCore import QCoreApplication, QObject, Signal

        if QCoreApplication.instance() is None:
            QCoreApplication([])
        host = QObject()

        class _Emitter(QObject):
            result_ready = Signal(dict)

        emitter = _Emitter()
        seen = []
        threading_utils.connect_on_receiver(
            emitter,
            "result_ready(QVariantMap)",
            host,
            lambda payload: seen.append(payload),
        )
        emitter.result_ready.emit({"ok": 1})
        self.assertEqual(seen, [{"ok": 1}])

    def test_object_and_string_signal_reaches_the_receiver_slot(self):
        from PySide6.QtCore import QCoreApplication, QObject, Signal

        if QCoreApplication.instance() is None:
            QCoreApplication([])

        class _Emitter(QObject):
            finished_export = Signal(object, str)

        emitter = _Emitter()
        host = QObject()
        seen = []
        threading_utils.connect_on_receiver(
            emitter,
            "finished_export(PyObject,QString)",
            host,
            lambda result, path: seen.append((result, path)),
        )
        emitter.finished_export.emit({"ok": True}, "D:/clip.mp4")
        self.assertEqual(seen, [({"ok": True}, "D:/clip.mp4")])
