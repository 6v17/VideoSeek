import os
import tempfile
import unittest
from unittest.mock import patch

from src.services import video_download_errors as vde
from src.services.legacy_network_cleanup_service import scan_legacy_network_assets
from src.services.remote_link_precheck_service import precheck_remote_links
from src.services import video_download_errors as vde
from src.services.video_download_service import (
    _build_cookie_attempts,
    _domains_from_url,
    _douyin_cookie_file_is_usable,
    _info_is_video_only,
    _refresh_browser_cookie_cache,
    build_download_format,
    extract_video_heights,
    format_qualities_label,
    get_browser_cookie_preflight_reason,
    get_download_default_dir,
    inspect_douyin_cookie_file,
    parse_links_from_text,
    probe_video_link,
    resolve_download_output_dir,
)


class VideoDownloadServiceTests(unittest.TestCase):
    def test_parse_links_from_text_deduplicates(self):
        raw = "https://www.youtube.com/watch?v=abc\nhttps://www.youtube.com/watch?v=abc\n"
        self.assertEqual(parse_links_from_text(raw), ["https://www.youtube.com/watch?v=abc"])

    def test_get_download_default_dir_uses_data_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            config = {"meta_file": os.path.join(data_dir, "meta.json")}
            path = get_download_default_dir(config)
            self.assertEqual(path, os.path.join(data_dir, "downloads"))

    def test_probe_invalid_url(self):
        result = probe_video_link("not-a-url")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason_code, vde.INVALID_URL)

    def test_probe_blocked_search_page(self):
        result = probe_video_link("https://www.youtube.com/results?search_query=cat")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason_code, vde.UNSUPPORTED_PAGE)

    @patch("src.services.video_download_service._extract_info")
    def test_probe_success(self, mock_extract):
        mock_extract.return_value = {
            "title": "Demo",
            "duration": 95,
            "thumbnail": "https://example.com/t.jpg",
            "extractor": "youtube",
            "vcodec": "avc1",
            "acodec": "mp4a",
        }
        result = probe_video_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertTrue(result.ok)
        self.assertEqual(result.title, "Demo")

    @patch("src.services.video_download_service._extract_info")
    def test_probe_audio_only_fails(self, mock_extract):
        mock_extract.return_value = {
            "title": "Audio",
            "duration": 10,
            "extractor": "youtube",
            "vcodec": "none",
            "acodec": "mp4a",
        }
        result = probe_video_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason_code, vde.AUDIO_ONLY)

    def test_info_is_video_only(self):
        self.assertTrue(
            _info_is_video_only({"vcodec": "avc1", "acodec": "none"}),
        )
        self.assertFalse(
            _info_is_video_only({"vcodec": "avc1", "acodec": "mp4a"}),
        )

    @patch("src.services.video_download_service.is_registered_library_path", return_value=True)
    def test_resolve_download_output_dir_library(self, _mock_registered):
        with tempfile.TemporaryDirectory() as lib:
            path = resolve_download_output_dir(mode="library", library_path=lib)
            expected_prefix = os.path.normcase(os.path.join(lib, "imports"))
            self.assertTrue(os.path.normcase(path).startswith(expected_prefix))
            self.assertTrue(os.path.isdir(path))

    def test_precheck_accepts_bilibili_video_page(self):
        result = precheck_remote_links(["https://www.bilibili.com/video/BV1xx411c7mD/"])
        self.assertEqual(result["accepted_count"], 1)

    def test_build_download_format_720(self):
        fmt = build_download_format("720")
        self.assertIn("height<=720", fmt)

    def test_bilibili_download_strategy(self):
        from src.services.video_download_service import _download_strategies_for_request, _is_bilibili_url

        self.assertTrue(_is_bilibili_url("https://www.bilibili.com/video/BV1xx411c7mD/"))
        strategies = _download_strategies_for_request(
            "https://www.bilibili.com/video/BV1xx411c7mD/",
            "best",
        )
        self.assertEqual(strategies[0]["id"], "bilibili_avc")
        self.assertIn("vcodec^=avc", strategies[0]["format"])

    def test_collect_probe_heights(self):
        from dataclasses import dataclass

        from src.services.video_download_service import ProbeResult, collect_probe_heights

        @dataclass
        class R:
            ok: bool
            video_heights: list[int]

        heights = collect_probe_heights(
            [
                ProbeResult(ok=True, url="a", video_heights=[1080, 720]),
                ProbeResult(ok=True, url="b", video_heights=[720, 480]),
                ProbeResult(ok=False, url="c", video_heights=[1080]),
            ]
        )
        self.assertEqual(heights, [1080, 720, 480])

    def test_extract_video_heights(self):
        info = {
            "formats": [
                {"vcodec": "avc1", "height": 1080},
                {"vcodec": "avc1", "height": 720},
                {"vcodec": "none", "height": 0},
            ]
        }
        self.assertEqual(extract_video_heights(info), [1080, 720])

    def test_build_cookie_attempts_includes_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
            handle.write(b"# Netscape HTTP Cookie File\n")
            path = handle.name
        try:
            attempts = _build_cookie_attempts(config={"download_cookie_file": path})
            self.assertEqual(attempts[0].get("cookiefile"), path)
            self.assertEqual(len(attempts), 2)
        finally:
            os.unlink(path)

    def test_build_cookie_attempts_prefers_file_over_browser(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
            handle.write(b"# Netscape HTTP Cookie File\n")
            path = handle.name
        try:
            attempts = _build_cookie_attempts(config={"download_cookie_file": path})
            self.assertNotIn("cookiesfrombrowser", attempts[0])
            self.assertFalse(any("cookiesfrombrowser" in item for item in attempts))
        finally:
            os.unlink(path)

    @patch("src.services.video_download_service._refresh_browser_cookie_cache", return_value=True)
    def test_build_cookie_attempts_uses_rookiepy_cache(self, _mock_refresh):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "edge.txt")
            with open(cache_path, "w", encoding="utf-8") as handle:
                handle.write("# Netscape HTTP Cookie File\n")
                handle.write(".example.com\tTRUE\t/\tTRUE\t2147483647\tsession\tdemo\n")
            with patch(
                "src.services.video_download_service._get_browser_cookie_cache_path",
                return_value=cache_path,
            ):
                attempts = _build_cookie_attempts(config={"meta_file": os.path.join(tmp, "meta.json")})
            self.assertEqual(attempts[0].get("cookiefile"), cache_path)
            self.assertIn("cookiesfrombrowser", attempts[1])

    def test_domains_from_url(self):
        self.assertEqual(
            _domains_from_url("https://www.bilibili.com/video/BV1xx411c7mD/"),
            ["bilibili.com"],
        )
        self.assertEqual(
            _domains_from_url("https://v.douyin.com/osId0ScbU80/"),
            ["douyin.com", "iesdouyin.com", "bytedance.com"],
        )

    @patch("src.services.video_download_service._rookiepy_loader")
    def test_refresh_browser_cookie_cache_writes_netscape(self, mock_loader):
        mock_loader.return_value = lambda domains: [
            {
                "domain": ".example.com",
                "path": "/",
                "secure": True,
                "expires": 2147483647,
                "name": "session",
                "value": "abc",
                "http_only": False,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "edge.txt")
            self.assertTrue(_refresh_browser_cookie_cache("edge", cache_path))
            with open(cache_path, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("Netscape HTTP Cookie File", content)
            self.assertIn("session\tabc", content)

    def test_inspect_douyin_cookie_file_requires_s_v_web_id(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as handle:
            handle.write("# Netscape HTTP Cookie File\n")
            handle.write(".douyin.com\tTRUE\t/\tTRUE\t2147483647\tttwid\tdemo\n")
            path = handle.name
        try:
            info = inspect_douyin_cookie_file(path)
            self.assertTrue(info["has_douyin_domain"])
            self.assertFalse(info["has_s_v_web_id"])
            self.assertFalse(_douyin_cookie_file_is_usable(path))
        finally:
            os.unlink(path)

    def test_probe_douyin_invalid_cookie_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as handle:
            handle.write("# Netscape HTTP Cookie File\n")
            handle.write(".douyin.com\tTRUE\t/\tTRUE\t2147483647\tttwid\tdemo\n")
            path = handle.name
        try:
            result = probe_video_link(
                "https://v.douyin.com/osId0ScbU80/",
                config={"download_cookie_file": path},
            )
            self.assertFalse(result.ok)
            self.assertEqual(result.reason_code, vde.DOUYIN_COOKIE_INVALID)
        finally:
            os.unlink(path)

    def test_parse_douyin_share_text(self):
        raw = (
            "4.10 oda:/ 09/24 M@w.FU :7pm 爱情公寓  "
            "https://v.douyin.com/osId0ScbU80/ 复制此链接，打开Dou音搜索，直接观看视频！"
        )
        self.assertEqual(parse_links_from_text(raw), ["https://v.douyin.com/osId0ScbU80/"])

    def test_map_exception_browser_cookie_locked(self):
        reason = vde.map_exception_to_reason(
            RuntimeError("Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271")
        )
        self.assertEqual(reason, vde.BROWSER_COOKIE_LOCKED)

    def test_map_exception_dpapi_decrypt(self):
        reason = vde.map_exception_to_reason(
            RuntimeError("Failed to decrypt with DPAPI. See https://github.com/yt-dlp/yt-dlp/issues/10927")
        )
        self.assertEqual(reason, vde.BROWSER_COOKIE_LOCKED)

    def test_map_exception_rookiepy_admin(self):
        reason = vde.map_exception_to_reason(
            RuntimeError("Chrome cookies from version v130 can be decrypted only when running as admin due to appbound encryption!")
        )
        self.assertEqual(reason, vde.BROWSER_COOKIE_LOCKED)

    @patch("src.services.video_download_service.is_windows_admin", return_value=False)
    def test_browser_cookie_preflight_warns_without_admin(self, _mock_admin):
        self.assertEqual(get_browser_cookie_preflight_reason(config={}), vde.BROWSER_COOKIE_LOCKED)

    @patch("src.services.video_download_service.is_windows_admin", return_value=True)
    def test_browser_cookie_preflight_ok_with_admin(self, _mock_admin):
        self.assertIsNone(get_browser_cookie_preflight_reason(config={}))

    @patch("src.services.video_download_service.is_windows_admin", return_value=False)
    def test_browser_cookie_preflight_ok_with_cookie_file(self, _mock_admin):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("# Netscape HTTP Cookie File\n")
            path = handle.name
        try:
            self.assertIsNone(get_browser_cookie_preflight_reason(config={"download_cookie_file": path}))
        finally:
            os.unlink(path)

    @patch("src.services.video_download_service._extract_info")
    def test_probe_includes_available_qualities(self, mock_extract):
        mock_extract.return_value = {
            "title": "Demo",
            "duration": 95,
            "extractor": "youtube",
            "vcodec": "avc1",
            "acodec": "mp4a",
            "formats": [
                {"vcodec": "avc1", "height": 1080},
                {"vcodec": "avc1", "height": 720},
            ],
        }
        result = probe_video_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertTrue(result.ok)
        self.assertIn("1080p", result.available_qualities)


class LegacyNetworkCleanupTests(unittest.TestCase):
    def test_scan_includes_legacy_remote_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            remote_dir = os.path.join(data_dir, "remote")
            os.makedirs(remote_dir, exist_ok=True)
            with open(os.path.join(remote_dir, "remote_index.faiss"), "wb") as handle:
                handle.write(b"test")
            config = {"meta_file": os.path.join(data_dir, "meta.json")}
            scan = scan_legacy_network_assets(config)
            self.assertIn(remote_dir, scan.paths)


if __name__ == "__main__":
    unittest.main()
