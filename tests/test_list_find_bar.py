"""Unit tests for lightweight list find matching."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from ui.widgets.list_find_bar import ListFindHit, collect_grouped_find_hits, entry_video_label


class ListFindHelpersTests(unittest.TestCase):
    def test_collect_matches_library_and_video_names(self):
        blocks = [
            SimpleNamespace(
                lib_path=r"D:\Media\Travel",
                entries=[
                    {"video_rel_path": "clips/beach.mp4", "video_id": "a"},
                    {"video_rel_path": "clips/city.mp4", "video_id": "b"},
                ],
            ),
            SimpleNamespace(
                lib_path=r"E:\Archive\Work",
                entries=[
                    {"video_rel_path": "demo_beach_cut.mp4", "video_id": "c"},
                ],
            ),
        ]

        hits = collect_grouped_find_hits(blocks, "beach")
        self.assertEqual(
            hits,
            [
                ListFindHit(0, 0),
                ListFindHit(1, 0),
            ],
        )

        lib_hits = collect_grouped_find_hits(blocks, "travel")
        self.assertEqual(lib_hits, [ListFindHit(0, -1)])

    def test_library_hits_are_ordered_before_video_hits(self):
        blocks = [
            SimpleNamespace(
                lib_path=r"D:\Media\Other",
                entries=[{"video_rel_path": "TravelNotes.mp4", "video_id": "v"}],
            ),
            SimpleNamespace(
                lib_path=r"D:\Media\Travel",
                entries=[{"video_rel_path": "clip.mp4", "video_id": "c"}],
            ),
        ]
        hits = collect_grouped_find_hits(blocks, "Travel")
        self.assertEqual(hits[0], ListFindHit(1, -1))
        self.assertIn(ListFindHit(0, 0), hits)

    def test_entry_video_label_prefers_basename(self):
        self.assertEqual(
            entry_video_label({"video_rel_path": r"folder\clip.mp4"}),
            "clip.mp4",
        )


if __name__ == "__main__":
    unittest.main()
