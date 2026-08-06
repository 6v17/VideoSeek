"""Tests for clipboard image → query path helpers."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from src.services.clipboard_image_service import is_image_file_path, resolve_clipboard_image_path


class ClipboardImageServiceTests(unittest.TestCase):
    def test_is_image_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.png")
            with open(path, "wb") as handle:
                handle.write(b"x")
            self.assertTrue(is_image_file_path(path))
            self.assertFalse(is_image_file_path(os.path.join(tmp, "a.txt")))
            self.assertFalse(is_image_file_path(""))

    def test_resolve_prefers_clipboard_image(self):
        fake_image = mock.Mock()
        fake_image.isNull.return_value = False
        clipboard = mock.Mock()
        mime = mock.Mock()
        mime.hasImage.return_value = True
        mime.hasUrls.return_value = False
        clipboard.mimeData.return_value = mime
        clipboard.image.return_value = fake_image
        with mock.patch(
            "src.services.clipboard_image_service.save_qimage_for_query",
            return_value=r"C:\tmp\paste.png",
        ) as save:
            path = resolve_clipboard_image_path(clipboard)
        self.assertEqual(path, r"C:\tmp\paste.png")
        save.assert_called_once_with(fake_image)

    def test_resolve_falls_back_to_local_image_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "shot.jpg")
            with open(path, "wb") as handle:
                handle.write(b"x")
            url = mock.Mock()
            url.toLocalFile.return_value = path
            mime = mock.Mock()
            mime.hasImage.return_value = False
            mime.hasUrls.return_value = True
            mime.urls.return_value = [url]
            clipboard = mock.Mock()
            clipboard.mimeData.return_value = mime
            resolved = resolve_clipboard_image_path(clipboard)
            self.assertEqual(resolved, path)


if __name__ == "__main__":
    unittest.main()
