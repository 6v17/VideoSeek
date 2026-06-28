import os
import unittest
from unittest.mock import patch

from src.services.remote_html_assets import inline_remote_html_images


class RemoteHtmlAssetsTests(unittest.TestCase):
    @patch(
        "src.services.remote_html_assets._fetch_image_data_uri",
        return_value="data:image/png;base64,abc123",
    )
    def test_inline_remote_html_images_replaces_https_src(self, _mock_fetch):
        html = "<img src=\"https://cdn.example.com/a.png\" width=\"200\" />"

        result = inline_remote_html_images(html)

        self.assertIn('src="data:image/png;base64,abc123"', result)
        self.assertIn('<a href="https://cdn.example.com/a.png">', result)

    @patch(
        "src.services.remote_html_assets._fetch_image_data_uri",
        return_value="data:image/png;base64,abc123",
    )
    def test_inline_remote_html_images_supports_single_quoted_src(self, _mock_fetch):
        html = "<img src='https://cdn.example.com/a.png' width='200' />"

        result = inline_remote_html_images(html)

        self.assertIn("src='data:image/png;base64,abc123'", result)

    @patch(
        "src.services.remote_html_assets._fetch_image_data_uri",
        side_effect=TimeoutError("timeout"),
    )
    def test_inline_remote_html_images_keeps_original_src_on_failure(self, _mock_fetch):
        html = "<img src='https://cdn.example.com/a.png' />"

        result = inline_remote_html_images(html)

        self.assertIn("https://cdn.example.com/a.png", result)
        self.assertIn('<a href="https://cdn.example.com/a.png">', result)

    @patch(
        "src.services.remote_html_assets._fetch_image_data_uri",
        return_value="data:image/png;base64,abc123",
    )
    def test_inline_remote_html_images_wraps_linked_images_once(self, _mock_fetch):
        html = "<a href='https://cdn.example.com/a.png'><img src='https://cdn.example.com/a.png' /></a>"

        result = inline_remote_html_images(html)

        self.assertEqual(result.count("<a "), 1)

    def test_is_probably_image_url(self):
        from src.services.remote_html_assets import is_probably_image_url

        self.assertTrue(is_probably_image_url("https://cdn.example.com/assets/wechat-reward.png"))
        self.assertFalse(is_probably_image_url("https://github.com/6v17/VideoSeek"))

    @patch("src.services.remote_html_assets.fetch_cached_bytes", return_value=b"png-bytes")
    def test_download_url_to_temp_file(self, _mock_fetch):
        from src.services.remote_html_assets import download_url_to_temp_file

        path = download_url_to_temp_file("https://cdn.example.com/a.png")

        self.assertTrue(path.endswith(".png"))
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"png-bytes")
        os.remove(path)


if __name__ == "__main__":
    unittest.main()
