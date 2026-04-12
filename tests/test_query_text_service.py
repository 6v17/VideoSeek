import unittest

from src.services.query_text_service import prepare_text_query


class QueryTextServiceTests(unittest.TestCase):
    def test_prepare_text_query_normalizes_spacing_and_punctuation(self):
        result = prepare_text_query("  夜晚，  街道上!!! 奔跑 的 男人  ")

        self.assertEqual(result["normalized"], "夜晚 街道上 奔跑 的 男人")
        self.assertTrue(result["changed"])
        self.assertFalse(result["too_short"])

    def test_prepare_text_query_marks_too_short(self):
        result = prepare_text_query("人")

        self.assertTrue(result["too_short"])
        self.assertEqual(result["normalized"], "人")

    def test_prepare_text_query_marks_generic(self):
        result = prepare_text_query("一个男的")

        self.assertTrue(result["generic"])
        self.assertFalse(result["too_short"])


if __name__ == "__main__":
    unittest.main()
