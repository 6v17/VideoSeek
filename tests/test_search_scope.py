import os
import tempfile
import unittest
from unittest.mock import patch

from src.domain.search_hit import SearchHit
from src.services.search_scope import (
    apply_search_scope,
    filter_hits_by_library_paths,
    filter_hits_by_video_paths,
    resolve_default_active_search_scope,
    resolve_effective_search_scope,
    resolve_explicit_scope_library_paths,
    resolve_fetch_top_k,
    scope_request_is_explicit,
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

    def test_scope_path_normalization_matches_tree_and_config(self):
        from src.services.search_scope import normalize_scope_path

        raw = "D:/Videos/Clip.mp4"
        tree_path = normalize_scope_path(raw)
        config_path = normalize_scope_path(os.path.normpath(raw))
        self.assertEqual(tree_path, config_path)
        self.assertIn(tree_path, {config_path})

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

    @patch("src.services.search_scope.resolve_active_search_video_scope", return_value=["D:/a.mp4"])
    def test_resolve_default_active_search_scope_prefers_videos(self, _mock_videos):
        videos, libraries = resolve_default_active_search_scope()
        self.assertEqual(videos, ["D:/a.mp4"])
        self.assertIsNone(libraries)

    @patch("src.storage.config_store.get_search_scope_video_paths", return_value=[])
    @patch("src.storage.config_store.get_search_scope_library_paths", return_value=["D:/lib"])
    @patch("src.storage.config_store.get_search_scope_mode", return_value="selected")
    @patch("src.services.library_service.needs_search_index_schema_upgrade", return_value=False)
    @patch("src.services.search_scope.per_library_indexes_ready", return_value=True)
    def test_resolve_active_search_video_scope_uses_library_index_when_ready(
        self,
        _mock_ready,
        _mock_upgrade,
        _mock_mode,
        _mock_libs,
        _mock_videos,
    ):
        from src.services.search_scope import resolve_active_search_video_scope

        self.assertIsNone(resolve_active_search_video_scope())

    @patch("src.storage.config_store.get_search_scope_video_paths", return_value=[])
    @patch("src.storage.config_store.get_search_scope_library_paths", return_value=["D:/lib"])
    @patch("src.storage.config_store.get_search_scope_mode", return_value="selected")
    @patch("src.services.library_service.needs_search_index_schema_upgrade", return_value=False)
    @patch("src.services.search_scope.per_library_indexes_ready", return_value=False)
    @patch("src.services.search_scope.list_ready_video_paths_for_libraries", return_value=["D:/lib/a.mp4"])
    def test_resolve_active_search_video_scope_expands_library_when_index_not_ready(
        self,
        _mock_expand,
        _mock_ready,
        _mock_upgrade,
        _mock_mode,
        _mock_libs,
        _mock_videos,
    ):
        from src.services.search_scope import resolve_active_search_video_scope

        self.assertEqual(resolve_active_search_video_scope(), ["D:/lib/a.mp4"])

    def test_resolve_explicit_scope_library_paths_explicit_wins(self):
        scope = {
            "library_paths": ["D:/explicit"],
            "use_saved_scope": True,
        }
        resolved = resolve_explicit_scope_library_paths(scope)
        self.assertEqual(resolved, ["D:/explicit"])

    def test_resolve_effective_search_scope_uses_preset_videos(self):
        videos, libraries = resolve_effective_search_scope(
            None,
            preset_scope_video_paths=["D:/preset.mp4"],
        )
        self.assertEqual(videos, ["D:/preset.mp4"])
        self.assertIsNone(libraries)


if __name__ == "__main__":
    unittest.main()
