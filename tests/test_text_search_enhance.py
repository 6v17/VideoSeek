"""Unit tests for text-search enhance helpers."""

from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

from src.domain.search_hit import SearchHit
from src.services.text_search_enhance import (
    expand_text_search_synonyms,
    extract_text_search_phrases,
    rrf_fuse_search_hits,
    select_text_search_routes,
    should_enhance_text_query,
)


class TextSearchEnhanceTests(unittest.TestCase):
    def test_extract_phrases_english_and_chinese(self):
        en = extract_text_search_phrases("a red car on the street")
        self.assertIn("red", en)
        self.assertIn("car", en)
        self.assertIn("street", en)
        self.assertNotIn("the", [p.casefold() for p in en])

        zh = extract_text_search_phrases("红衣女人在柜台")
        self.assertTrue(any("女人" in p or p == "女人" for p in zh) or "红衣女人" in zh)
        joined = "".join(zh)
        self.assertIn("柜台", joined)

    def test_expand_synonyms_cn_en(self):
        expanded = expand_text_search_synonyms(["狗", "car"])
        self.assertIn("狗", expanded)
        self.assertIn("dog", expanded)
        self.assertIn("car", expanded)
        self.assertTrue({"车", "汽车"} & set(expanded))

    def test_select_routes_keeps_query_first(self):
        query = "红衣女人 狗"
        # Fake embeddings: query vector; phrases get slight variants.
        base = np.array([1.0, 0.0, 0.0], dtype=np.float32)

        def embed_fn(text: str):
            body = str(text)
            if body == query:
                return base
            if "狗" in body or body.casefold() == "dog":
                return np.array([0.9, 0.4, 0.0], dtype=np.float32)
            if "女人" in body or "woman" in body.casefold():
                return np.array([0.85, 0.0, 0.5], dtype=np.float32)
            return np.array([0.2, 0.2, 0.2], dtype=np.float32)

        routes = select_text_search_routes(query, embed_fn=embed_fn, max_extra=3)
        self.assertGreaterEqual(len(routes), 1)
        self.assertEqual(routes[0], query)
        self.assertLessEqual(len(routes), 4)

    def test_rrf_fuse_prefers_multi_route_agreement(self):
        a = SearchHit(1.0, 2.0, 0.9, "a.mp4", match_kind="frame", video_id="v1")
        b = SearchHit(3.0, 4.0, 0.95, "b.mp4", match_kind="frame", video_id="v2")
        c = SearchHit(1.0, 2.0, 0.5, "a.mp4", match_kind="frame", video_id="v1")
        fused = rrf_fuse_search_hits([[b, a], [c]], top_k=2)
        self.assertEqual(len(fused), 2)
        self.assertEqual(fused[0].video_path, "a.mp4")

    def test_should_enhance_gates(self):
        self.assertFalse(
            should_enhance_text_query(
                is_text=True, query_data="dog", query_vector=None, enabled=False
            )
        )
        self.assertFalse(
            should_enhance_text_query(
                is_text=False, query_data="dog", query_vector=None, enabled=True
            )
        )
        self.assertFalse(
            should_enhance_text_query(
                is_text=True,
                query_data="dog",
                query_vector=np.zeros((1, 3)),
                enabled=True,
            )
        )
        self.assertTrue(
            should_enhance_text_query(
                is_text=True, query_data="dog", query_vector=None, enabled=True
            )
        )

    def test_run_search_skips_enhance_when_disabled(self):
        from src.services import search_service

        with mock.patch.object(
            search_service,
            "get_text_search_enhance_enabled",
            return_value=False,
        ), mock.patch.object(
            search_service,
            "_run_enhanced_text_search",
        ) as enhance, mock.patch.object(
            search_service,
            "_run_search_impl",
            return_value=[],
        ), mock.patch(
            "src.services.search_scope.filter_hits_with_existing_sources",
            side_effect=lambda hits, **_kwargs: hits,
        ), mock.patch(
            "src.services.search_scope.load_searchable_path_index",
            return_value={},
        ), mock.patch.object(
            search_service,
            "load_config",
            return_value={"search_mode": "frame", "search_top_k": 10},
        ), mock.patch.object(
            search_service,
            "get_search_mode",
            return_value="frame",
        ), mock.patch.object(
            search_service,
            "_use_precise_image_pipeline",
            return_value=False,
        ), mock.patch.object(
            search_service,
            "is_profiling_enabled",
            return_value=False,
        ), mock.patch.object(
            search_service,
            "build_profile_meta_from_config",
            return_value={},
        ), mock.patch.object(
            search_service,
            "set_search_progress_callback",
        ), mock.patch.object(
            search_service,
            "clear_search_progress_callback",
        ), mock.patch.object(
            search_service,
            "_reset_search_index_steps",
        ):
            search_service.run_search("红衣女人", is_text=True, top_k=5)
        enhance.assert_not_called()

    def test_run_mixed_query_search_uses_multi_route_when_enhanced(self):
        from src.services import search_service

        hit_a = SearchHit(1.0, 2.0, 0.9, "a.mp4", video_id="v1")
        hit_b = SearchHit(3.0, 4.0, 0.8, "b.mp4", video_id="v2")

        with mock.patch.object(
            search_service,
            "get_text_search_enhance_enabled",
            return_value=True,
        ), mock.patch.object(
            search_service,
            "load_config",
            return_value={"search_mode": "frame", "search_top_k": 5},
        ), mock.patch.object(
            search_service,
            "get_search_mode",
            return_value="frame",
        ), mock.patch.object(
            search_service,
            "get_search_top_k",
            return_value=5,
        ), mock.patch(
            "src.services.search_preset_query.encode_mixed_query_vector",
            return_value=np.array([[1.0, 0.0]], dtype=np.float32),
        ), mock.patch(
            "src.services.text_search_enhance.select_text_search_routes",
            return_value=["红衣女人 狗", "狗", "女人"],
        ), mock.patch.object(
            search_service,
            "run_search",
            side_effect=[[hit_a], [hit_a, hit_b], [hit_b]],
        ) as run_search:
            out = search_service.run_mixed_query_search(
                query="红衣女人 狗",
                source_image_paths=[],
                fusion={"text_weight": 0.5, "image_weight": 0.5},
                top_k=2,
                text_enhance=True,
            )
        self.assertEqual(run_search.call_count, 3)
        self.assertTrue(out)
        self.assertEqual(out[0].video_path, "a.mp4")


if __name__ == "__main__":
    unittest.main()
