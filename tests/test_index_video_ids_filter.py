import os
import tempfile
import unittest
from unittest import mock

from src.services.indexing_service import _collect_library_scan_plan, _library_meta_has_any_video_id
from src.services.library_scan_selection import plan_library_scan_paths


class IndexVideoIdsFilterTests(unittest.TestCase):
    def test_plan_keeps_only_selected_video_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            keep = os.path.join(tmp, "keep.mp4")
            skip = os.path.join(tmp, "skip.mp4")
            open(keep, "wb").close()
            open(skip, "wb").close()
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
            open(keep, "wb").close()
            open(skip, "wb").close()
            planned = plan_library_scan_paths(
                tmp,
                {"keep.mp4": {"vid": "a"}, "skip.mp4": {"vid": "b"}},
                [keep, skip],
                None,
            )
            self.assertEqual(planned, [keep, skip])

    def test_plan_matches_forward_slash_meta_keys_on_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = os.path.join(tmp, "season", "keep.mp4")
            os.makedirs(os.path.dirname(nested), exist_ok=True)
            open(nested, "wb").close()
            # Meta / SQLite keys use forward slashes; relpath on Windows uses backslash.
            lib_files = {"season/keep.mp4": {"vid": "vid_keep"}}
            planned = plan_library_scan_paths(
                tmp,
                lib_files,
                [nested],
                {"vid_keep"},
            )
            self.assertEqual(planned, [nested])

    def test_plan_resolves_from_meta_when_discover_rel_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = os.path.join(tmp, "season", "keep.mp4")
            os.makedirs(os.path.dirname(nested), exist_ok=True)
            open(nested, "wb").close()
            lib_files = {"season/keep.mp4": {"vid": "vid_keep"}}
            # Pretend discover returned nothing usable for key matching.
            planned = plan_library_scan_paths(
                tmp,
                lib_files,
                [],
                {"vid_keep"},
            )
            self.assertEqual(planned, [nested])

    def test_plan_empty_selection_stays_empty_without_crash(self):
        planned = plan_library_scan_paths("/tmp", {"a.mp4": {"vid": "x"}}, [], {"missing"})
        self.assertEqual(planned, [])

    def test_plan_missing_ids_do_not_log_error(self):
        with self.assertLogs("videoseek.library_scan_selection", level="DEBUG") as captured:
            planned = plan_library_scan_paths(
                "/tmp",
                {"a.mp4": {"vid": "x"}},
                [],
                {"missing"},
            )
        self.assertEqual(planned, [])
        self.assertTrue(
            any("no hits in library" in line for line in captured.output),
            captured.output,
        )
        self.assertFalse(any("| ERROR |" in line or " ERROR:" in line for line in captured.output))

    def test_collect_plan_skips_libraries_without_selected_ids(self):
        with tempfile.TemporaryDirectory() as keep_root, tempfile.TemporaryDirectory() as skip_root:
            keep_file = os.path.join(keep_root, "keep.mp4")
            open(keep_file, "wb").close()
            meta = {
                "libraries": {
                    keep_root: {"files": {"keep.mp4": {"vid": "keep_id"}}},
                    skip_root: {"files": {"other.mp4": {"vid": "other_id"}}},
                }
            }
            with mock.patch(
                "src.services.indexing_service.discover_video_files_incremental",
                side_effect=lambda root, _lib: [os.path.join(root, "keep.mp4")] if root == keep_root else [],
            ):
                plan = _collect_library_scan_plan(meta, selected_video_ids={"keep_id"})
            self.assertEqual([root for root, _lib, _files in plan], [keep_root])
            self.assertTrue(_library_meta_has_any_video_id(meta["libraries"][keep_root], {"keep_id"}))
            self.assertFalse(_library_meta_has_any_video_id(meta["libraries"][skip_root], {"keep_id"}))


if __name__ == "__main__":
    unittest.main()
