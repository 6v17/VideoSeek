import unittest

from PySide6.QtCore import QUrl

from ui.dialogs.html_links import is_external_link


class HtmlLinksTests(unittest.TestCase):
    def test_is_external_link_detects_http_urls(self):
        self.assertTrue(is_external_link(QUrl("https://github.com/6v17/VideoSeek")))
        self.assertTrue(is_external_link("https://example.com"))
        self.assertTrue(is_external_link("//cdn.example.com/image.png"))

    def test_is_external_link_ignores_in_document_anchors(self):
        self.assertFalse(is_external_link("#section"))
        self.assertFalse(is_external_link(""))

    def test_is_external_link_ignores_local_resources(self):
        self.assertFalse(is_external_link(QUrl("file:///C:/tmp/readme.txt")))


if __name__ == "__main__":
    unittest.main()
