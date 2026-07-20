import os
import tempfile
import unittest
from unittest.mock import patch

from src.domain.search_hit import SearchHit
from src.services.search_scope import (
    SearchablePathIndex,
    apply_search_scope,
    filter_hits_by_library_paths,
    filter_hits_by_video_paths,
    filter_hits_with_existing_sources,
    resolve_default_active_search_scope,
    resolve_effective_search_scope,
    resolve_explicit_scope_library_paths,
    resolve_fetch_top_k,
    scope_request_is_explicit,
    video_path_under_library_root,
    video_source_exists,
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

    def test_resolve_source_filtered_fetch_top_k_expands_global_recall(self):
        from src.services.search_fetch_policy import resolve_source_filtered_fetch_top_k

        self.assertEqual(resolve_source_filtered_fetch_top_k(20, False), 100)
        self.assertEqual(resolve_source_filtered_fetch_top_k(20, True), 500)

    @patch("src.services.search_scope.video_source_exists", return_value=True)
    def test_apply_search_scope_trims_top_k(self, _mock_exists):
        hits = [
            SearchHit(float(i), float(i), 1.0 - i * 0.1, f"D:/clip_{i}.mp4")
            for i in range(5)
        ]
        trimmed = apply_search_scope(hits, top_k=2)
        self.assertEqual(len(trimmed), 2)

    def test_filter_hits_with_existing_sources(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            existing_path = handle.name
        try:
            hits = [
                SearchHit(1.0, 1.0, 0.9, existing_path),
                SearchHit(2.0, 2.0, 0.8, "D:/missing/clip.mp4"),
                SearchHit(3.0, 3.0, 0.7, ""),
            ]
            filtered = filter_hits_with_existing_sources(hits)
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0].video_path, existing_path)
        finally:
            os.unlink(existing_path)

    def test_filter_hits_with_existing_sources_resolves_stale_lance_path(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            existing_path = handle.name
        try:
            meta = {
                "libraries": {
                    os.path.dirname(existing_path): {
                        "files": {
                            os.path.basename(existing_path): {
                                "vid": "v1",
                                "asset_state": "ready",
                            }
                        }
                    }
                }
            }
            path_index = SearchablePathIndex.from_meta(meta)
            hits = [
                SearchHit(
                    1.0,
                    1.0,
                    0.9,
                    "D:/old/moved/clip.mp4",
                    video_id="v1",
                    matched_text="line",
                )
            ]
            filtered = filter_hits_with_existing_sources(hits, path_index=path_index)
            self.assertEqual(len(filtered), 1)
            from src.services.search_scope import normalize_scope_path

            self.assertEqual(normalize_scope_path(filtered[0].video_path), normalize_scope_path(existing_path))
            self.assertEqual(filtered[0].matched_text, "line")
        finally:
            os.unlink(existing_path)

    def test_enrich_hits_with_source_paths_via_subtitle_index(self):
        from src.services.search_scope import enrich_hits_with_source_paths

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            existing_path = handle.name
        try:
            subtitle_index = SearchablePathIndex(
                by_video_id={"sub1": existing_path},
                by_normalized_path={},
            )
            with patch(
                "src.services.search_scope.load_searchable_path_index",
                return_value=SearchablePathIndex(by_video_id={}, by_normalized_path={}),
            ), patch(
                "src.services.search_scope.load_subtitle_searchable_path_index",
                return_value=subtitle_index,
            ):
                hits = enrich_hits_with_source_paths(
                    [SearchHit(1.0, 2.0, 1.0, "", video_id="sub1", matched_text="hi")]
                )
            self.assertEqual(len(hits), 1)
            from src.services.search_scope import normalize_scope_path

            self.assertEqual(normalize_scope_path(hits[0].video_path), normalize_scope_path(existing_path))
            self.assertEqual(hits[0].matched_text, "hi")
        finally:
            os.unlink(existing_path)

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

    @patch("src.storage.asset_store.save_metadata")
    @patch(
        "src.storage.asset_store.get_model_profile_storage_paths",
        return_value={"meta_file": "D:/meta.json"},
    )
    def test_save_model_metadata_invalidates_path_index_cache(self, _mock_paths, _mock_save):
        import src.services.search_scope as search_scope
        from src.storage.asset_store import save_model_metadata

        search_scope._PATH_INDEX_CACHE["D:/meta.json"] = (
            1.0,
            SearchablePathIndex(by_video_id={}, by_normalized_path={}),
        )
        save_model_metadata({})
        self.assertEqual(search_scope._PATH_INDEX_CACHE, {})


if __name__ == "__main__":
    unittest.main()
