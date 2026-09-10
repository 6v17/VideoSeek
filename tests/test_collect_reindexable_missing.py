import unittest
from unittest.mock import patch

import tests.services_test_support  # noqa: F401 - cv2/faiss stubs
from src.services.library_service import collect_reindexable_missing_video_ids


class CollectReindexableMissingTests(unittest.TestCase):
    @patch("src.services.library_service.list_library_video_entries")
    @patch("src.services.library_service.load_config", return_value={})
    def test_collects_missing_and_broken_with_source(self, _mock_cfg, mock_entries):
        mock_entries.return_value = [
            {"video_id": "a", "source_exists": True, "asset_state": "missing_asset"},
            {"video_id": "b", "source_exists": True, "asset_state": "broken_asset"},
            {"video_id": "c", "source_exists": False, "asset_state": "missing_asset"},
            {"video_id": "d", "source_exists": True, "asset_state": "missing_source"},
            {"video_id": "e", "source_exists": True, "asset_state": "sync_failed"},
            {"video_id": "f", "source_exists": True, "asset_state": "ready"},
            {"video_id": "a", "source_exists": True, "asset_state": "missing_asset"},
            {"video_id": "", "source_exists": True, "asset_state": "missing_asset"},
            "skip-me",
        ]
        self.assertEqual(collect_reindexable_missing_video_ids(), ["a", "b"])

    @patch("src.services.library_service.list_library_video_entries", return_value=[])
    @patch("src.services.library_service.load_config", return_value={})
    def test_empty_when_none(self, _mock_cfg, _mock_entries):
        self.assertEqual(collect_reindexable_missing_video_ids(), [])


if __name__ == "__main__":
    unittest.main()
