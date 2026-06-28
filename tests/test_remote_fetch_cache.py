import json
import os
import shutil
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from src.services import remote_fetch_cache


class RemoteFetchCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    @patch("src.services.remote_fetch_cache.get_app_data_dir")
    def test_returns_fresh_cache_without_network(self, mock_get_app_data_dir):
        mock_get_app_data_dir.return_value = self.temp_dir
        url = "https://cdn.example.com/notice.json"
        body_path, meta_path = remote_fetch_cache._cache_paths(remote_fetch_cache._cache_dir(), url)
        os.makedirs(os.path.dirname(body_path), exist_ok=True)
        with open(body_path, "wb") as handle:
            handle.write(b'{"ok": true}')
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "url": url,
                    "fetched_at": time.time(),
                    "expires_at": time.time() + 3600,
                },
                handle,
            )

        with patch("urllib.request.urlopen") as mock_urlopen:
            payload = remote_fetch_cache.fetch_cached_bytes(url, kind="json")

        self.assertEqual(payload, b'{"ok": true}')
        mock_urlopen.assert_not_called()

    @patch("src.services.remote_fetch_cache.get_app_data_dir")
    def test_uses_conditional_headers_when_cache_expired(self, mock_get_app_data_dir):
        mock_get_app_data_dir.return_value = self.temp_dir
        url = "https://cdn.example.com/notice.json"
        body_path, meta_path = remote_fetch_cache._cache_paths(remote_fetch_cache._cache_dir(), url)
        os.makedirs(os.path.dirname(body_path), exist_ok=True)
        with open(body_path, "wb") as handle:
            handle.write(b'{"old": true}')
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "url": url,
                    "etag": '"abc123"',
                    "last_modified": "Sun, 01 Jan 2024 00:00:00 GMT",
                    "fetched_at": time.time() - 7200,
                    "expires_at": time.time() - 60,
                    "last_attempt_at": time.time() - 7200,
                },
                handle,
            )

        response = MagicMock()
        response.status = 304
        response.headers = {}
        with patch("urllib.request.urlopen", return_value=MagicMock(__enter__=lambda *_: response, __exit__=lambda *_: None)) as mock_urlopen:
            payload = remote_fetch_cache.fetch_cached_bytes(url, kind="json")

        self.assertEqual(payload, b'{"old": true}')
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.get_header("If-none-match"), '"abc123"')
        self.assertEqual(request.get_header("If-modified-since"), "Sun, 01 Jan 2024 00:00:00 GMT")

    @patch("src.services.remote_fetch_cache.get_app_data_dir")
    def test_returns_stale_cache_on_network_failure(self, mock_get_app_data_dir):
        mock_get_app_data_dir.return_value = self.temp_dir
        url = "https://cdn.example.com/notice.json"
        body_path, meta_path = remote_fetch_cache._cache_paths(remote_fetch_cache._cache_dir(), url)
        os.makedirs(os.path.dirname(body_path), exist_ok=True)
        with open(body_path, "wb") as handle:
            handle.write(b'{"stale": true}')
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "url": url,
                    "fetched_at": time.time() - 120,
                    "expires_at": time.time() - 60,
                    "last_attempt_at": time.time() - 7200,
                },
                handle,
            )

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            payload = remote_fetch_cache.fetch_cached_bytes(url, kind="json")

        self.assertEqual(payload, b'{"stale": true}')

    @patch("src.services.remote_fetch_cache.get_app_data_dir")
    def test_respects_refetch_cooldown_without_cache_body(self, mock_get_app_data_dir):
        mock_get_app_data_dir.return_value = self.temp_dir
        url = "https://cdn.example.com/notice.json"
        _, meta_path = remote_fetch_cache._cache_paths(remote_fetch_cache._cache_dir(), url)
        os.makedirs(os.path.dirname(meta_path), exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "url": url,
                    "fetched_at": time.time() - 7200,
                    "expires_at": time.time() - 60,
                    "last_attempt_at": time.time() - 30,
                },
                handle,
            )

        with patch("urllib.request.urlopen") as mock_urlopen:
            payload = remote_fetch_cache.fetch_cached_bytes(url, kind="json")

        self.assertIsNone(payload)
        mock_urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
