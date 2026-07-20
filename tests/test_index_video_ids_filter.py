import os
import tempfile
import unittest

from src.services.library_scan_selection import plan_library_scan_paths


class IndexVideoIdsFilterTests(unittest.TestCase):
    def test_plan_keeps_only_selected_video_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            keep = os.path.join(tmp, "keep.mp4")
            skip = os.path.join(tmp, "skip.mp4")
            lib_files = {
                "keep.mp4": {"vid": "vid_keep"},
                "skip.mp4": {"vid": "vid_skip"},
            }
            planned = plan_library_scan_paths(
                tmp,
                lib_files,
                [keep, skip],
                {"vid_keep"},
            )
            self.assertEqual(planned, [keep])

    def test_plan_none_keeps_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            keep = os.path.join(tmp, "keep.mp4")
            skip = os.path.join(tmp, "skip.mp4")
            planned = plan_library_scan_paths(
                tmp,
                {"keep.mp4": {"vid": "a"}, "skip.mp4": {"vid": "b"}},
                [keep, skip],
                None,
            )
            self.assertEqual(planned, [keep, skip])


if __name__ == "__main__":
    unittest.main()
