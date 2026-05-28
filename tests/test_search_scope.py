import os
import tempfile
import unittest

from src.domain.search_hit import SearchHit
from src.services.search_scope import (
    apply_search_scope,
    filter_hits_by_library_paths,
    filter_hits_by_video_paths,
    resolve_fetch_top_k,
    video_path_under_library_root,
)


class SearchScopeTests(unittest.TestCase):
    def test_resolve_fetch_top_k_expands_when_scoped(self):
        self.assertEqual(resolve_fetch_top_k(20, False), 20)
        self.assertEqual(resolve_fetch_top_k(20, True), 100)

    def test_filter_hits_by_video_paths(self):
        hits = [
            SearchHit(1.0, 1.0, 0.9, "D:/keep.mp4"),
            SearchHit(2.0, 2.0, 0.8, "D:/drop.mp4"),
        ]
        filtered = filter_hits_by_video_paths(hits, ["D:/keep.mp4"])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].video_path, "D:/keep.mp4")

    def test_filter_hits_by_library_paths(self):
        with tempfile.TemporaryDirectory() as lib_a, tempfile.TemporaryDirectory() as lib_b:
            hit_a = SearchHit(1.0, 1.0, 0.9, os.path.join(lib_a, "clip.mp4"))
            hit_b = SearchHit(2.0, 2.0, 0.8, os.path.join(lib_b, "clip.mp4"))
            filtered = filter_hits_by_library_paths([hit_a, hit_b], [lib_a])
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0].video_path, hit_a.video_path)

    def test_video_path_under_library_root(self):
        with tempfile.TemporaryDirectory() as lib_root:
            nested = os.path.join(lib_root, "nested", "clip.mp4")
            self.assertTrue(video_path_under_library_root(nested, lib_root))
            self.assertTrue(video_path_under_library_root(lib_root, lib_root))
            self.assertFalse(video_path_under_library_root("D:/other/clip.mp4", lib_root))

    def test_apply_search_scope_trims_top_k(self):
        hits = [
            SearchHit(float(i), float(i), 1.0 - i * 0.1, f"D:/clip_{i}.mp4")
            for i in range(5)
        ]
        trimmed = apply_search_scope(hits, top_k=2)
        self.assertEqual(len(trimmed), 2)


if __name__ == "__main__":
    unittest.main()
