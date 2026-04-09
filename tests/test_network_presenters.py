import unittest

from src.app.i18n import get_texts
from ui.network_build_presenter import format_build_finished_status, format_build_progress_text
from ui.network_precheck_presenter import build_precheck_dialog_payload


class NetworkPrecheckPresenterTests(unittest.TestCase):
    def test_build_precheck_dialog_payload_builds_rows_and_subtitle(self):
        texts = get_texts("en")
        precheck = {
            "accepted_count": 2,
            "blocked_count": 1,
            "risky_count": 1,
            "blocked_links": [{"link": "https://example.com/search?q=abc", "reason": "unsupported_page_type"}],
            "risky_links": [{"link": "https://v.douyin.com/abc/", "reason": "site_may_require_cookie_or_video_page"}],
        }

        payload = build_precheck_dialog_payload(precheck, texts)

        self.assertEqual(payload["title"], texts["network_precheck_dialog_title"])
        self.assertIn("Accepted 2", payload["subtitle"])
        self.assertEqual(len(payload["rows"]), 2)
        self.assertEqual(payload["rows"][0][1], texts["network_precheck_status_blocked"])
        self.assertEqual(payload["rows"][1][1], texts["network_precheck_status_risky"])


class NetworkBuildPresenterTests(unittest.TestCase):
    def test_format_build_progress_text_maps_known_patterns(self):
        texts = get_texts("en")

        self.assertIn(
            "extracting frames",
            format_build_progress_text("Extracting frames 2/9", texts).lower(),
        )
        self.assertIn(
            "indexed 12 frames",
            format_build_progress_text("Indexed 12 frames from source 2/9", texts).lower(),
        )
        self.assertEqual(
            format_build_progress_text("Building FAISS index", texts),
            texts["network_build_progress_building"],
        )

    def test_format_build_finished_status_contains_summary_counts(self):
        texts = get_texts("en")
        status = {
            "new_vectors": 0,
            "total_vectors": 345,
            "success_count": 3,
            "failed_count": 1,
            "skipped_count": 2,
        }

        rendered = format_build_finished_status(status, texts)

        self.assertIn("+0 vectors", rendered)
        self.assertIn("success 3", rendered.lower())
        self.assertIn("failed 1", rendered.lower())
        self.assertIn("skipped 2", rendered.lower())


if __name__ == "__main__":
    unittest.main()
