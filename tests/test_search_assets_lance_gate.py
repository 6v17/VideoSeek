"""search_assets messaging when Lance is missing."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from src.services import search_assets


class SearchAssetsMissingLanceTests(unittest.TestCase):
    def setUp(self):
        search_assets.invalidate_search_asset_caches()

    @patch("src.services.search_assets.logger")
    @patch("src.storage.video_id_migration.legacy_npy_vectors_present", return_value=True)
    @patch("src.services.search_assets.lance_search_is_ready", return_value=False)
    @patch("src.services.search_assets.get_local_model_asset_dirs", return_value={"base_dir": "D:/profile"})
    def test_load_search_assets_errors_when_legacy_npy_present(
        self,
        _mock_dirs,
        _mock_ready,
        _mock_legacy,
        mock_logger,
    ):
        result = search_assets.load_search_assets({})

        self.assertEqual(result, (None, None, None))
        mock_logger.error.assert_called()
        message = str(mock_logger.error.call_args.args[0])
        self.assertIn("legacy npy", message.lower())

    @patch("src.services.search_assets.logger")
    @patch("src.storage.video_id_migration.legacy_npy_vectors_present", return_value=False)
    @patch("src.services.search_assets.lance_search_is_ready", return_value=False)
    @patch("src.services.search_assets.get_local_model_asset_dirs", return_value={"base_dir": "D:/profile"})
    def test_load_search_assets_warns_when_no_legacy_npy(
        self,
        _mock_dirs,
        _mock_ready,
        _mock_legacy,
        mock_logger,
    ):
        result = search_assets.load_search_assets({})

        self.assertEqual(result, (None, None, None))
        mock_logger.warning.assert_called()
        mock_logger.error.assert_not_called()

    def test_frame_asset_cache_hits_without_import_state_file(self):
        sentinel = object()
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("src.services.search_assets.lance_search_is_ready", return_value=True),
                patch(
                    "src.services.search_assets.get_local_model_asset_dirs",
                    return_value={"base_dir": temp_dir},
                ),
                patch(
                    "src.services.search_assets.load_lance_frame_search_assets",
                    return_value=(sentinel, None, None),
                ) as load_assets,
            ):
                first = search_assets.load_search_assets({})
                second = search_assets.load_search_assets({})

        self.assertIs(first[0], sentinel)
        self.assertIs(second[0], sentinel)
        self.assertEqual(load_assets.call_count, 1)


if __name__ == "__main__":
    unittest.main()
