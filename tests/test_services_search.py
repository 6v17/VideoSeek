import unittest
from unittest.mock import patch

import numpy as np

import tests.services_test_support  # noqa: F401 - cv2/faiss stubs
from src.domain.search_hit import SearchHit
from src.services import search_service


class SearchServiceTests(unittest.TestCase):
    @patch("src.services.search_service.faiss.normalize_L2", create=True)
    @patch("src.services.search_service.get_text_embedding")
    def test_build_query_vector_for_text(self, mock_text_embedding, mock_normalize):
        mock_text_embedding.return_value = np.array([[1.0, 2.0]], dtype=np.float32)

        result = search_service.build_query_vector("cat on sofa", is_text=True)

        self.assertEqual(result.dtype, np.float32)
        mock_normalize.assert_called_once()

    @patch("src.services.search_service.load_search_assets")
    @patch("src.services.search_service.build_query_vector")
    @patch("src.services.search_service._search_frame_results_with_ids")
    @patch("src.services.search_service.load_config")
    def test_run_search_returns_empty_when_index_missing(
        self,
        mock_load_config,
        mock_search_results_with_ids,
        mock_build_query_vector,
        mock_load_assets,
    ):
        mock_load_config.return_value = {"cross_index_file": "index.faiss", "cross_vector_file": "vectors.npy"}
        mock_load_assets.return_value = (None, None, None)

        result = search_service.run_search("query", is_text=True)

        self.assertEqual(result, [])
        mock_build_query_vector.assert_called_once()
        mock_search_results_with_ids.assert_not_called()

    @patch(
        "src.services.search_scope.filter_hits_with_existing_sources",
        side_effect=lambda hits, **_kwargs: list(hits or []),
    )
    @patch(
        "src.services.search_service._coalesce_query_vector",
        return_value=np.array([[1.0, 0.0]], dtype=np.float32),
    )
    @patch("src.services.search_service._run_frame_search_per_videos")
    @patch("src.services.search_service.load_config")
    def test_run_search_uses_per_video_route_when_video_scope_set(
        self,
        mock_load_config,
        mock_per_video_search,
        _mock_coalesce_query_vector,
        _mock_filter_existing,
    ):
        from src.domain.search_hit import SearchHit

        mock_load_config.return_value = {}
        expected = [SearchHit(1.0, 1.0, 0.8, "D:/clip.mp4")]
        mock_per_video_search.return_value = expected

        result = search_service.run_search(
            "query",
            is_text=True,
            top_k=5,
            search_mode="frame",
            scope_video_paths=["D:/clip.mp4"],
        )

        self.assertEqual(result, expected)
        mock_per_video_search.assert_called_once()

    @patch("src.services.search_service.run_chunk_search")
    @patch("src.services.search_service._run_search_impl")
    @patch("src.services.search_service.load_config")
    def test_run_search_image_defaults_to_frame_when_mode_unset(
        self,
        mock_load_config,
        mock_run_impl,
        mock_run_chunk,
    ):
        mock_load_config.return_value = {"search_mode": "chunk"}
        mock_run_impl.return_value = []

        search_service.run_search("img.jpg", is_text=False, search_mode=None)

        mock_run_chunk.assert_not_called()
        mock_run_impl.assert_called_once()
        self.assertEqual(mock_run_impl.call_args.kwargs["mode"], "frame")

    @patch(
        "src.services.search_scope.filter_hits_with_existing_sources",
        side_effect=lambda hits, **_kwargs: list(hits or []),
    )
    @patch("src.services.search_service.build_query_vector", return_value=np.array([[1.0, 0.0]], dtype=np.float32))
    @patch("src.services.search_service._run_frame_search_per_videos")
    @patch("src.services.search_service.load_config")
    def test_run_search_uses_per_video_route_for_precise_scoped_image(
        self,
        mock_load_config,
        mock_per_video_search,
        _mock_build_query_vector,
        _mock_filter_existing,
    ):
        from src.domain.search_hit import SearchHit

        mock_load_config.return_value = {}
        expected = [SearchHit(12.0, 12.0, 0.91, "D:/clip.mp4")]
        mock_per_video_search.return_value = expected

        result = search_service.run_search(
            "D:/query.jpg",
            is_text=False,
            top_k=5,
            scope_video_paths=["D:/clip.mp4"],
            search_precision_mode="precise",
        )

        self.assertEqual(result, expected)
        mock_per_video_search.assert_called_once()
        self.assertTrue(mock_per_video_search.call_args.kwargs.get("precise_image"))

    def test_check_asset_profile_compatibility_is_noop_under_lance(self):
        asset_info = {
            "embedding_spec": {
                "model_id": "clip_onnx_default",
                "provider": "clip_onnx",
                "embedding_space": "clip_onnx_default",
                "dimension": 512,
                "metric": "ip",
            },
            "index_dim": 512,
        }

        search_service._check_asset_profile_compatibility({}, asset_info, asset_label="frame")

    def test_check_asset_profile_compatibility_ignores_missing_embedding_spec(self):
        asset_info = {"embedding_spec": None, "index_dim": 512}

        search_service._check_asset_profile_compatibility({}, asset_info, asset_label="frame")

    def test_apply_frame_neighbor_rerank_disabled_by_default(self):
        class DummyIndex:
            def reconstruct(self, idx):
                return np.array([1.0, 0.0], dtype=np.float32)

        results = [SearchHit(1.0, 1.0, 0.8, "a.mp4")]
        frame_ids = [1]
        query_vector = np.array([[1.0, 0.0]], dtype=np.float32)
        timestamps = np.array([0.0, 1.0, 2.0], dtype=np.float32)
        paths = np.array(["a.mp4", "a.mp4", "a.mp4"], dtype=object)

        reranked = search_service._apply_frame_neighbor_rerank(
            results,
            frame_ids,
            query_vector,
            DummyIndex(),
            timestamps,
            paths,
            config={},
            is_text=True,
        )
        self.assertEqual(reranked, results)

    def test_neighbor_rerank_auto_enabled_for_image_search(self):
        self.assertFalse(search_service._neighbor_rerank_enabled({}, is_text=False, precise_image=True))
        self.assertFalse(search_service._neighbor_rerank_enabled({}, is_text=False, precise_image=False))

    def test_neighbor_rerank_respects_text_default(self):
        self.assertFalse(search_service._neighbor_rerank_enabled({}, is_text=True))

    def test_neighbor_rerank_disabled_for_fast_image_search(self):
        self.assertFalse(search_service._neighbor_rerank_enabled({}, is_text=False, precise_image=False))

    @patch("src.services.search_locate_pipeline.apply_image_pixel_rerank")
    def test_finalize_frame_hits_prefers_pixel_query_data(self, mock_pixel):
        mock_pixel.return_value = []
        hits = [SearchHit(1.0, 1.0, 0.9, "a.mp4")]
        search_service._finalize_frame_hits(
            "text query",
            False,
            hits,
            5,
            {},
            precise_image=True,
            pixel_query_data="/path/to/ref.jpg",
        )
        mock_pixel.assert_called_once()
        self.assertEqual(mock_pixel.call_args[0][0], "/path/to/ref.jpg")

    def test_collect_neighbor_frame_ids_uses_time_window(self):
        timestamps = np.array([10.0, 11.0, 12.0, 13.0, 20.0], dtype=np.float32)
        paths = np.array(["a.mp4"] * 4 + ["b.mp4"], dtype=object)
        ids = search_service._collect_neighbor_frame_ids(2, timestamps, paths, window_sec=1.5)
        self.assertEqual(ids, [2, 1, 3])

    def test_apply_frame_neighbor_rerank_snaps_to_better_neighbor(self):
        class DummyIndex:
            def __init__(self):
                self._vectors = {
                    0: np.array([0.6, 0.8], dtype=np.float32),
                    1: np.array([0.8, 0.2], dtype=np.float32),
                    2: np.array([1.0, 0.0], dtype=np.float32),
                }

            def reconstruct(self, idx):
                return self._vectors[idx]

        results = [SearchHit(1.0, 1.0, 0.8, "a.mp4")]
        frame_ids = [1]
        query_vector = np.array([[1.0, 0.0]], dtype=np.float32)
        timestamps = np.array([0.0, 1.0, 2.0], dtype=np.float32)
        paths = np.array(["a.mp4", "a.mp4", "a.mp4"], dtype=object)
        config = {
            "frame_neighbor_rerank_enabled": True,
            "frame_neighbor_rerank_top_n": 5,
            "frame_neighbor_rerank_window": 2,
        }

        reranked = search_service._apply_frame_neighbor_rerank(
            results,
            frame_ids,
            query_vector,
            DummyIndex(),
            timestamps,
            paths,
            config=config,
        )
        self.assertEqual(reranked[0].start_sec, 2.0)
        self.assertEqual(reranked[0].end_sec, 2.0)
        self.assertGreater(reranked[0].score, results[0].score)




if __name__ == "__main__":
    unittest.main()
