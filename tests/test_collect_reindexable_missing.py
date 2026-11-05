import unittest
from unittest.mock import patch

import tests.services_test_support  # noqa: F401 - cv2/faiss stubs
from src.services.library_service import (
    _effective_asset_state,
    _unsynced_library_display_state,
    collect_reindexable_missing_video_ids,
)


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
            {"video_id": "g", "source_exists": True, "asset_state": "pending"},
            {"video_id": "a", "source_exists": True, "asset_state": "missing_asset"},
            {"video_id": "", "source_exists": True, "asset_state": "missing_asset"},
            "skip-me",
        ]
        self.assertEqual(collect_reindexable_missing_video_ids(), ["a", "b"])

    @patch("src.services.library_service.list_library_video_entries", return_value=[])
    @patch("src.services.library_service.load_config", return_value={})
    def test_empty_when_none(self, _mock_cfg, _mock_entries):
        self.assertEqual(collect_reindexable_missing_video_ids(), [])

    @patch("src.services.library_service.list_library_video_entries")
    @patch("src.services.library_service.load_config", return_value={})
    def test_reuses_provided_entries_without_rescanning(self, _mock_cfg, mock_entries):
        entries = [
            {"video_id": "x", "source_exists": True, "asset_state": "missing_asset"},
            {"video_id": "y", "source_exists": True, "asset_state": "ready"},
        ]
        self.assertEqual(collect_reindexable_missing_video_ids(entries=entries), ["x"])
        mock_entries.assert_not_called()

    @patch("src.services.library_service.list_library_video_entries")
    @patch("src.services.library_service.load_config", return_value={})
    def test_ready_never_force_queued(self, _mock_cfg, mock_entries):
        mock_entries.return_value = [
            {"video_id": "old", "source_exists": True, "asset_state": "ready"},
            {"video_id": "ok", "source_exists": True, "asset_state": "ready"},
        ]
        self.assertEqual(collect_reindexable_missing_video_ids(), [])

    def test_pending_is_not_a_lost_index(self):
        self.assertEqual(
            _effective_asset_state(
                {"asset_state": "pending"},
                source_exists=True,
                vector_exists=False,
                vector_ok=True,
                lance_ready=False,
            ),
            "pending",
        )
        self.assertEqual(
            _effective_asset_state(
                {"asset_state": "ready"},
                source_exists=True,
                vector_exists=False,
                vector_ok=True,
                lance_ready=False,
            ),
            "missing_asset",
        )
        self.assertEqual(
            _unsynced_library_display_state("missing_asset", "missing_asset", "pending"),
            "pending",
        )
        self.assertEqual(
            _unsynced_library_display_state("missing_asset", "missing_asset", "ready"),
            "missing_asset",
        )


if __name__ == "__main__":
    unittest.main()
