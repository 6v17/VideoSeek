import tempfile
import unittest
from unittest.mock import patch

from src.services.shot_list_export_service import (
    build_manifest_items_from_shot_list,
    build_shot_list_batch_export_items,
)
from src.services.shot_list_service import ShotListItem


class ShotListExportServiceTests(unittest.TestCase):
    def _sample_items(self):
        return [
            ShotListItem("a", "D:/lib/ep01.mp4", 10.0, 15.0, 0.82, source_query="smile"),
            ShotListItem("b", "D:/lib/ep02.mp4", 3.5, 8.0, 0.71),
        ]

    def test_build_manifest_items(self):
        rows = build_manifest_items_from_shot_list(self._sample_items())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["query"], "smile")
        self.assertEqual(rows[1]["rank"], 2)
        self.assertEqual(rows[0]["video_path"], "D:/lib/ep01.mp4")

    def test_build_batch_export_items_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.services.shot_list_export_service._normalize_export_output_dir", return_value=tmp):
                items = build_shot_list_batch_export_items(self._sample_items(), tmp)
            self.assertEqual(len(items), 2)
            self.assertTrue(items[0].output_path.endswith("01_ep01_10.mp4"))
            self.assertTrue(items[1].output_path.endswith("02_ep02_3.mp4"))


if __name__ == "__main__":
    unittest.main()
