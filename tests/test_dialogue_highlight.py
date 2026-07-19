import unittest


class DialogueHighlightTests(unittest.TestCase):
    def test_fuzzy_colors_scatter_chars_unordered(self):
        from ui.views.dialogue_highlight import highlight_dialogue_html

        html = highlight_dialogue_html(
            "了杀都在这里",
            "都杀了",
            match_mode="fuzzy",
            color="#ff0000",
        )
        self.assertIn('style="color:#ff0000;font-weight:700"', html)
        self.assertIn(">了杀都<", html)

    def test_exact_colors_contiguous_span(self):
        from ui.views.dialogue_highlight import highlight_dialogue_html

        html = highlight_dialogue_html(
            "Hello World",
            "world",
            match_mode="exact",
            color="#00ff00",
        )
        self.assertIn('style="color:#00ff00;font-weight:700">World</span>', html)
        self.assertIn("Hello ", html)

    def test_escapes_html_in_subtitle(self):
        from ui.views.dialogue_highlight import highlight_dialogue_html

        html = highlight_dialogue_html(
            "<b>赞</b>",
            "赞",
            match_mode="fuzzy",
            color="#123456",
        )
        self.assertNotIn("<b>", html)
        self.assertIn("&lt;b&gt;", html)


if __name__ == "__main__":
    unittest.main()
