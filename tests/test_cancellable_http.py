import json
import threading
import time
import unittest
import urllib.request
from unittest.mock import MagicMock, patch

from src.core.understanding.base import UnderstandingStoppedError
from src.services.cancellable_http import urlopen_json_with_stop


class CancellableHttpTests(unittest.TestCase):
    def test_returns_json_body(self):
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps({"ok": True}).encode("utf-8")
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)
        request = urllib.request.Request("http://example.test/v1", data=b"{}", method="POST")
        with patch("urllib.request.urlopen", return_value=fake_response):
            body = urlopen_json_with_stop(request, timeout_sec=5.0)
        self.assertEqual(body, {"ok": True})

    def test_stop_during_inflight_closes_response_and_returns_quickly(self):
        release = threading.Event()
        closed = threading.Event()
        stop_after = threading.Event()

        class _BlockingResponse:
            def read(self):
                stop_after.set()
                release.wait(timeout=30)
                return b'{"ok": true}'

            def close(self):
                closed.set()
                release.set()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def _urlopen(*_args, **_kwargs):
            return _BlockingResponse()

        stop = {"flag": False}

        def _should_stop():
            return stop["flag"]

        request = urllib.request.Request("http://example.test/v1", data=b"{}", method="POST")
        started = time.monotonic()
        with patch("urllib.request.urlopen", side_effect=_urlopen):
            def _arm_stop():
                self.assertTrue(stop_after.wait(timeout=2.0))
                stop["flag"] = True

            arm = threading.Thread(target=_arm_stop, daemon=True)
            arm.start()
            with self.assertRaises(UnderstandingStoppedError):
                urlopen_json_with_stop(
                    request,
                    timeout_sec=30.0,
                    should_stop_callback=_should_stop,
                    stop_message="stopped",
                )
            arm.join(timeout=2.0)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 5.0)
        self.assertTrue(closed.wait(timeout=2.0))


if __name__ == "__main__":
    unittest.main()
