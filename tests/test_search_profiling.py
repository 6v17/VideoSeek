import unittest

from src.services.search_profiling import (
    SearchProfileReport,
    format_search_profile,
    search_profile_session,
)


class SearchProfilingTests(unittest.TestCase):
    def test_format_search_profile_empty(self):
        text = format_search_profile(None, language="zh")
        self.assertIn("尚无性能报告", text)

    def test_profile_session_records_phases(self):
        with search_profile_session(
            enabled=True,
            search_mode="frame",
            precise_image=True,
            meta={"fetch_multiplier": 3, "neighbor_top_n": 10, "pixel_top_n": 20, "pixel_window_sec": 2.0},
        ) as report:
            self.assertIsNotNone(report)
            report.phases["faiss_search"] = 120
            report.phases["pixel_rerank"] = 300
            report.result_count = 5

        text = format_search_profile(report, language="zh")
        self.assertIn("FAISS 召回", text)
        self.assertIn("像素重排", text)
        self.assertIn("120 ms", text)
        self.assertNotIn("fetch_multiplier", text)


if __name__ == "__main__":
    unittest.main()
