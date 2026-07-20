import unittest

from ui.widgets.tooltip_utils import format_wrapped_tooltip


class TooltipUtilsTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(format_wrapped_tooltip(""), "")
        self.assertEqual(format_wrapped_tooltip(None), "")

    def test_wraps_plain_text_and_escapes(self):
        tip = format_wrapped_tooltip("一次竖向拼合<a>")
        self.assertIn("data-videoseek-tooltip", tip)
        self.assertIn("max-width:360px", tip)
        self.assertIn("一次竖向拼合&lt;a&gt;", tip)
        self.assertNotIn("<a>", tip)

    def test_preserves_newlines(self):
        tip = format_wrapped_tooltip("a\nb")
        self.assertIn("a<br/>b", tip)

    def test_idempotent_for_rich_text(self):
        first = format_wrapped_tooltip("hello")
        self.assertEqual(format_wrapped_tooltip(first), first)
        html = "<html><body>x</body></html>"
        self.assertEqual(format_wrapped_tooltip(html), html)


if __name__ == "__main__":
    unittest.main()
