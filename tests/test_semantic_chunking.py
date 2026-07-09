import unittest
from unittest.mock import patch

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None
if np is not None and not hasattr(np, "asarray"):  # pragma: no cover
    np = None

from src.domain.search_hit import SearchHit


def _schema_v2_config(**extra):
    """Minimal config valid for config_store.get_active_model_profile (schema >= 2)."""
    base = {
        "schema_version": 2,
        "models": {
            "active_profile": "clip_onnx_default",
            "profiles": [
                {
                    "id": "clip_onnx_default",
                    "provider": "clip_onnx",
                    "display_name": "CLIP ONNX",
                    "enabled": True,
                    "runtime": {
                        "prefer_gpu": True,
                        "model_dir": "",
                        "model_variant": "vit-base-patch32",
                    },
                    "files": {},
                    "capabilities": {
                        "text_query": True,
                        "image_query": True,
                        "video_embedding": True,
                        "cross_modal_search": True,
                    },
                },
            ],
        },
    }
    base.update(extra)
    return base


if np is not None:
    from src.core.semantic_chunking import (
        SPLIT_MAX_DURATION,
        build_semantic_chunks,
        build_semantic_chunks_streaming,
        merge_short_chunks,
        normalize_chunk_config_snapshot,
        unpack_chunks,
    )
    from src.services import indexing_service
    from src.services import search_service
else:  # pragma: no cover
    build_semantic_chunks = None
    unpack_chunks = None
    indexing_service = None
    search_service = None


@unittest.skipIf(np is None, "numpy is required for semantic chunking tests")
class SemanticChunkingTests(unittest.TestCase):
    def test_dual_check_splits_on_sharp_cut(self):
        embeddings = np.asarray(
            [
                [1.0, 0.0],
                [0.98, 0.02],
                [0.0, 1.0],
                [0.02, 0.98],
            ],
            dtype=np.float32,
        )
        timestamps = [0.0, 1.0, 2.0, 3.0]

        chunks = build_semantic_chunks(
            embeddings,
            timestamps,
            similarity_threshold=0.85,
            min_chunk_size=2,
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0.0, 1.0))
        self.assertEqual((chunks[1]["start"], chunks[1]["end"]), (2.0, 3.0))

    def test_dual_check_keeps_chunk_when_mean_similarity_recovers(self):
        embeddings = np.asarray(
            [
                [1.0, 0.0],
                [0.98, 0.02],
                [0.90, 0.10],
                [0.97, 0.03],
            ],
            dtype=np.float32,
        )
        timestamps = [0.0, 1.0, 2.0, 3.0]

        chunks = build_semantic_chunks(
            embeddings,
            timestamps,
            similarity_threshold=0.85,
            min_chunk_size=2,
        )

        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0.0, 3.0))

    def test_streaming_chunks_match_single_pass(self):
        embeddings = np.asarray(
            [
                [1.0, 0.0],
                [0.98, 0.02],
                [0.0, 1.0],
                [0.02, 0.98],
                [0.01, 0.99],
            ],
            dtype=np.float32,
        )
        timestamps = [0.0, 1.0, 2.0, 3.0, 4.0]
        kwargs = {
            "similarity_threshold": 0.85,
            "min_chunk_size": 2,
            "min_chunk_duration": 0.0,
        }

        single = build_semantic_chunks(embeddings, timestamps, **kwargs)
        streaming = build_semantic_chunks_streaming(
            [embeddings[:2], embeddings[2:4], embeddings[4:]],
            timestamps,
            **kwargs,
        )

        self.assertEqual(len(single), len(streaming))
        for left, right in zip(single, streaming):
            self.assertEqual((left["start"], left["end"]), (right["start"], right["end"]))
            np.testing.assert_allclose(left["embedding"], right["embedding"], rtol=1e-5, atol=1e-5)

    def test_identical_frames_stay_in_one_chunk(self):
        embeddings = np.asarray([[1.0, 0.0]] * 12, dtype=np.float32)
        timestamps = [float(index) for index in range(12)]

        chunks = build_semantic_chunks(embeddings, timestamps, similarity_threshold=0.85)

        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0.0, 11.0))

    def test_gradual_drift_splits_when_core_and_fringe_checks_fail(self):
        embeddings = np.asarray(
            [
                [1.0, 0.0],
                [0.98, 0.02],
                [0.70, 0.71],
                [0.69, 0.72],
            ],
            dtype=np.float32,
        )
        timestamps = [0.0, 1.0, 2.0, 3.0]

        chunks = build_semantic_chunks(
            embeddings,
            timestamps,
            similarity_threshold=0.85,
            chunk_edge_threshold=0.80,
            min_chunk_size=2,
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0.0, 1.0))
        self.assertEqual((chunks[1]["start"], chunks[1]["end"]), (2.0, 3.0))

    def test_fringe_does_not_become_adjacent_anchor(self):
        embeddings = np.asarray(
            [
                [1.0, 0.0],
                [0.98, 0.02],
                [0.86, 0.14],
                [0.97, 0.03],
            ],
            dtype=np.float32,
        )
        timestamps = [0.0, 1.0, 2.0, 3.0]

        chunks = build_semantic_chunks(
            embeddings,
            timestamps,
            similarity_threshold=0.85,
            chunk_edge_threshold=0.80,
            min_chunk_size=2,
        )

        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0.0, 3.0))

    def test_adjacent_check_uses_core_last_frame_not_fringe(self):
        """Frame 3 matches fringe frame 2, but split anchor stays core frame 1."""
        embeddings = np.asarray(
            [
                [1.0, 0.0],
                [0.98, 0.02],
                [0.86, 0.14],
                [0.85, 0.15],
                [0.0, 1.0],
            ],
            dtype=np.float32,
        )
        timestamps = [0.0, 1.0, 2.0, 3.0, 4.0]

        chunks = build_semantic_chunks(
            embeddings,
            timestamps,
            similarity_threshold=0.85,
            chunk_edge_threshold=0.80,
            min_chunk_size=2,
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0.0, 3.0))
        self.assertEqual((chunks[1]["start"], chunks[1]["end"]), (4.0, 4.0))

    def test_one_shot_mean_recovery_does_not_chain_unbounded_fringe(self):
        angles = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
        embeddings = np.asarray(
            [[np.cos(angle), np.sin(angle)] for angle in angles],
            dtype=np.float32,
        )
        timestamps = [float(index) for index in range(len(angles))]

        chunks = build_semantic_chunks(
            embeddings,
            timestamps,
            similarity_threshold=0.90,
            chunk_edge_threshold=0.80,
            min_chunk_size=2,
        )

        self.assertGreater(len(chunks), 1)
        self.assertLess(max(chunk["end"] - chunk["start"] for chunk in chunks), 3.0)

    def test_merge_short_chunks_combines_short_tail(self):
        records = [
            {
                "start": 0.0,
                "end": 1.0,
                "vectors": [np.asarray([1.0, 0.0], dtype=np.float32)],
                "times": [0.0],
            },
            {
                "start": 1.0,
                "end": 1.5,
                "vectors": [np.asarray([0.98, 0.02], dtype=np.float32)],
                "times": [1.5],
            },
        ]

        merged = merge_short_chunks(records, min_duration=2.0)

        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0]["start"], merged[0]["end"]), (0.0, 1.5))
        self.assertEqual(len(merged[0]["vectors"]), 2)

    def test_chunk_bounds_use_min_max_timestamp_with_transition(self):
        from src.core.semantic_chunking import SemanticChunkStreamBuilder

        builder = SemanticChunkStreamBuilder(
            similarity_threshold=0.90,
            chunk_edge_threshold=0.88,
            min_chunk_size=2,
        )
        vectors = np.asarray(
            [
                [1.0, 0.0],
                [0.98, 0.02],
                [0.84, 0.16],
            ],
            dtype=np.float32,
        )
        builder.extend(vectors, [34.0, 35.0, 36.0])
        builder._transition_vector = vectors[2]
        builder._transition_time = 40.0
        chunks = builder.finish()

        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (34.0, 40.0))

    def test_max_duration_fuse_splits_long_segment(self):
        embeddings = np.asarray([[1.0, 0.0]] * 5, dtype=np.float32)
        timestamps = [0.0, 30.0, 60.0, 90.0, 120.0]

        chunks = build_semantic_chunks(
            embeddings,
            timestamps,
            similarity_threshold=0.99,
            chunk_edge_threshold=0.97,
            min_chunk_size=2,
            max_chunk_duration=90.0,
        )

        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(max(chunk["end"] - chunk["start"] for chunk in chunks), 90.0)
        self.assertIn(SPLIT_MAX_DURATION, {chunk.get("split_reason") for chunk in chunks})

    def test_normalize_chunk_config_snapshot_ignores_retired_keys(self):
        normalized = normalize_chunk_config_snapshot(
            {
                "similarity_threshold": 0.85,
                "min_chunk_size": 2,
                "min_chunk_duration": 0.0,
                "max_chunk_duration": 45.0,
                "chunk_merge_adjacent_threshold": 0.9,
            }
        )
        self.assertEqual(
            normalized,
            {
                "similarity_threshold": 0.85,
                "chunk_edge_threshold": 0.83,
                "min_chunk_size": 2,
                "min_chunk_duration": 0.0,
                "max_chunk_duration": 45.0,
                "algorithm_version": 0,
            },
        )

    def test_normalize_chunk_config_snapshot_uses_current_algorithm_version(self):
        from src.core.semantic_chunking import CHUNK_ALGORITHM_VERSION

        normalized = normalize_chunk_config_snapshot(
            {
                "similarity_threshold": 0.85,
                "min_chunk_size": 2,
                "min_chunk_duration": 0.0,
                "algorithm_version": CHUNK_ALGORITHM_VERSION,
            }
        )
        self.assertEqual(normalized["algorithm_version"], CHUNK_ALGORITHM_VERSION)

    def test_chunk_builder_kwargs_ignores_algorithm_version(self):
        from src.core.semantic_chunking import CHUNK_ALGORITHM_VERSION, chunk_builder_kwargs

        kwargs = chunk_builder_kwargs(
            {
                "similarity_threshold": 0.88,
                "chunk_edge_threshold": 0.83,
                "min_chunk_size": 3,
                "min_chunk_duration": 1.5,
                "algorithm_version": CHUNK_ALGORITHM_VERSION,
            }
        )
        self.assertEqual(
            kwargs,
            {
                "similarity_threshold": 0.88,
                "chunk_edge_threshold": 0.83,
                "min_chunk_size": 3,
                "min_chunk_duration": 1.5,
                "max_chunk_duration": 90.0,
            },
        )


@unittest.skipIf(np is None, "numpy is required for semantic chunking tests")
class IndexingChunkUpgradeTests(unittest.TestCase):
    @patch("src.storage.lance_store.should_use_lance_storage", return_value=True)
    @patch("src.storage.lance_store.get_stored_chunk_config", return_value=None)
    @patch("src.storage.lance_search_index.load_lance_video_chunks", return_value=[])
    @patch("src.storage.lance_store.upsert_profile_video_vectors_from_arrays")
    @patch("src.storage.lance_search_index.load_lance_video_frame_arrays")
    @patch("src.services.indexing_service.get_local_model_asset_dirs")
    def test_load_video_chunks_by_id_builds_chunks_from_existing_vectors(
        self,
        mock_model_dirs,
        mock_load_lance_frames,
        mock_upsert_lance,
        _mock_load_lance_chunks,
        _mock_stored_config,
        _mock_should_lance,
    ):
        mock_model_dirs.return_value = {
            "base_dir": "base",
            "meta_file": "meta.json",
            "vector_dir": "source/vector",
            "index_dir": "index",
        }
        mock_load_lance_frames.return_value = (
            np.asarray([[1.0, 0.0], [0.99, 0.01]], dtype=np.float32),
            np.asarray([0.0, 1.0], dtype=np.float32),
        )
        config = _schema_v2_config(
            similarity_threshold=0.85,
            min_chunk_size=2,
        )

        chunks = indexing_service.load_video_chunks_by_id("video-1", config)

        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0.0, 1.0))
        mock_upsert_lance.assert_called_once()

    @patch("src.storage.lance_store.should_use_lance_storage", return_value=True)
    @patch("src.storage.lance_store.get_stored_chunk_config")
    @patch("src.storage.lance_search_index.load_lance_video_chunks")
    @patch("src.storage.lance_store.upsert_profile_video_vectors_from_arrays")
    @patch("src.storage.lance_search_index.load_lance_video_frame_arrays")
    @patch("src.services.indexing_service.get_local_model_asset_dirs")
    def test_load_video_chunks_by_id_rebuilds_when_algorithm_version_changes(
        self,
        mock_model_dirs,
        mock_load_lance_frames,
        mock_upsert_lance,
        mock_load_lance_chunks,
        mock_stored_config,
        _mock_should_lance,
    ):
        mock_model_dirs.return_value = {
            "base_dir": "base",
            "meta_file": "meta.json",
            "vector_dir": "source/vector",
            "index_dir": "index",
        }
        mock_load_lance_frames.return_value = (
            np.asarray([[1.0, 0.0], [0.99, 0.01], [0.0, 1.0], [0.01, 0.99]], dtype=np.float32),
            np.asarray([0.0, 1.0, 2.0, 3.0], dtype=np.float32),
        )
        mock_load_lance_chunks.return_value = [
            {"start": 0.0, "end": 3.0, "embedding": np.asarray([1.0, 0.0], dtype=np.float32)},
        ]
        mock_stored_config.return_value = {
            "similarity_threshold": 0.85,
            "min_chunk_size": 2,
            "min_chunk_duration": 0.0,
        }
        config = _schema_v2_config(
            similarity_threshold=0.85,
            min_chunk_size=2,
        )

        chunks = indexing_service.load_video_chunks_by_id("video-1", config)

        self.assertEqual(len(chunks), 2)
        mock_upsert_lance.assert_called_once()

    def test_unpack_chunks_reconstructs_chunk_list(self):
        payload = {
            "start": np.asarray([0.0, 2.0], dtype=np.float32),
            "end": np.asarray([1.0, 3.0], dtype=np.float32),
            "embedding": np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        }

        chunks = unpack_chunks(payload)

        self.assertEqual(len(chunks), 2)
        self.assertEqual((chunks[0]["start"], chunks[1]["end"]), (0.0, 3.0))


@unittest.skipIf(np is None, "numpy is required for semantic chunking tests")
class ChunkSearchTests(unittest.TestCase):
    @patch("src.services.search_assets.load_lance_chunk_search_assets")
    @patch("src.services.search_assets.lance_search_is_ready", return_value=True)
    @patch(
        "src.services.search_assets.get_local_model_asset_dirs",
        return_value={"base_dir": "source/profile"},
    )
    def test_load_chunk_search_assets_reads_ranges(
        self, _mock_dirs, _mock_ready, mock_load_lance
    ):
        mock_load_lance.return_value = (
            object(),
            np.asarray([[0.0, 1.0]], dtype=np.float32),
            ["video.mp4"],
        )

        from src.services import search_service

        index, ranges, paths = search_service.load_chunk_search_assets(_schema_v2_config())

        self.assertIsNotNone(index)
        self.assertEqual(ranges.shape, (1, 2))
        self.assertEqual(paths, ["video.mp4"])

    @patch("src.services.search_assets.load_lance_frame_search_assets")
    @patch("src.services.search_assets.lance_search_is_ready", return_value=True)
    @patch(
        "src.services.search_assets.get_local_model_asset_dirs",
        return_value={"base_dir": "source/profile"},
    )
    def test_load_search_assets_reads_timestamps(
        self, _mock_dirs, _mock_ready, mock_load_lance
    ):
        mock_load_lance.return_value = (
            object(),
            np.asarray([0.0], dtype=np.float32),
            ["video.mp4"],
        )

        from src.services import search_service

        index, timestamps, paths = search_service.load_search_assets(_schema_v2_config())

        self.assertIsNotNone(index)
        self.assertEqual(timestamps.shape, (1,))
        self.assertEqual(paths, ["video.mp4"])

    @patch("src.services.search_scope.filter_hits_with_existing_sources", side_effect=lambda hits, **kwargs: hits)
    @patch("src.services.search_service.run_chunk_search")
    @patch("src.services.search_service.load_config", return_value={"search_mode": "chunk", "search_top_k": 20})
    def test_run_search_dispatches_to_chunk_mode(
        self,
        _mock_load_config,
        mock_run_chunk_search,
        _mock_filter_hits,
    ):
        mock_run_chunk_search.return_value = [SearchHit(0.0, 0.0, 0.0, "chunk.mp4")]
        result = search_service.run_search("query", is_text=True, top_k=5)

        self.assertEqual(result, [SearchHit(0.0, 0.0, 0.0, "chunk.mp4")])
        mock_run_chunk_search.assert_called_once()
        _, kwargs = mock_run_chunk_search.call_args
        self.assertEqual(kwargs["top_k"], 5)
        self.assertIsNone(kwargs["scope_video_paths"])
        self.assertIsNone(kwargs["scope_library_paths"])

    def test_aggregate_frame_hits_to_chunks_groups_by_segment(self):
        from src.services.search_scope import normalize_scope_path

        video_path = "D:/lib/a.mp4"
        range_index = {
            normalize_scope_path(video_path): [
                (0.0, 4.0),
                (4.0, 10.0),
            ]
        }
        frame_hits = [
            SearchHit(1.0, 1.0, 0.7, video_path),
            SearchHit(2.0, 2.0, 0.9, video_path),
            SearchHit(6.0, 6.0, 0.8, video_path),
        ]
        with patch("src.services.search_chunk_pipeline._load_global_chunk_ranges_by_path", return_value=range_index):
            aggregated = search_service._aggregate_frame_hits_to_chunks(frame_hits, 5, {})
        self.assertEqual(len(aggregated), 2)
        self.assertAlmostEqual(float(aggregated[0].score), 0.9)
        self.assertAlmostEqual(float(aggregated[0].start_sec), 0.0)
        self.assertAlmostEqual(float(aggregated[0].end_sec), 4.0)
        self.assertAlmostEqual(float(aggregated[1].score), 0.8)
        self.assertAlmostEqual(float(aggregated[1].start_sec), 4.0)

    @patch("src.services.search_chunk_pipeline._aggregate_frame_hits_to_chunks", return_value=[])
    @patch("src.services.search_chunk_pipeline._collect_frame_candidates_for_chunk_search")
    def test_chunk_image_search_falls_back_to_frame_hits(self, mock_collect, _mock_aggregate):
        mock_collect.return_value = [SearchHit(12.0, 12.0, 0.91, "D:/lib/a.mp4")]
        results = search_service._run_chunk_search_via_frames(
            "D:/query.jpg",
            is_text=False,
            top_k=5,
            precise_image=True,
            config={"search_top_k": 5},
        )
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(float(results[0].start_sec), 12.0)
        self.assertAlmostEqual(float(results[0].score), 0.91)

    def test_prepare_frame_candidates_keeps_neighbor_pool_for_aggregate(self):
        video_path = "D:/lib/a.mp4"
        neighbor_hit = SearchHit(2.0, 2.0, 0.95, video_path)
        seed_hit = SearchHit(1.0, 1.0, 0.7, video_path)
        fillers = [
            SearchHit(float(i + 10), float(i + 10), 0.96, f"D:/lib/filler{i}.mp4")
            for i in range(120)
        ]
        hits = [seed_hit, neighbor_hit, *fillers]
        prepared = search_service._prepare_frame_candidates_for_chunk_aggregate(hits)
        prepared_by_video = {
            (str(hit.video_path), float(hit.start_sec))
            for hit in prepared
        }
        self.assertIn((video_path, 1.0), prepared_by_video)
        self.assertIn((video_path, 2.0), prepared_by_video)

    @patch("src.services.search_chunk_pipeline._check_asset_profile_compatibility")
    @patch("src.services.search_chunk_pipeline.load_search_assets")
    @patch("src.services.search_chunk_pipeline._search_frame_results_with_ids")
    def test_collect_frame_candidates_expands_neighbors_for_chunk_aggregate(
        self,
        mock_search,
        mock_load_assets,
        _mock_check_profile,
    ):
        class DummyIndex:
            def reconstruct(self, idx):
                vectors = {
                    0: np.array([0.8, 0.2], dtype=np.float32),
                    1: np.array([1.0, 0.0], dtype=np.float32),
                    2: np.array([0.2, 0.8], dtype=np.float32),
                }
                return vectors[int(idx)]

        video_path = "D:/lib/a.mp4"
        timestamps = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        paths = np.array([video_path, video_path, video_path], dtype=object)
        mock_load_assets.return_value = (DummyIndex(), timestamps, paths)
        mock_search.return_value = (
            [SearchHit(1.0, 1.0, 0.8, video_path)],
            [0],
        )
        config = {
            "frame_neighbor_rerank_enabled": True,
            "frame_neighbor_rerank_top_n": 5,
            "frame_neighbor_rerank_window": 2,
            "fps": 1.0,
        }
        query_vector = np.array([[1.0, 0.0]], dtype=np.float32)
        hits = search_service._collect_frame_candidates_for_chunk_search(
            "D:/query.jpg",
            is_text=False,
            top_k=5,
            query_vector=query_vector,
            precise_image=False,
            config=config,
        )
        hit_times = sorted(float(hit.start_sec) for hit in hits if hit.video_path == video_path)
        self.assertIn(1.0, hit_times)
        self.assertIn(2.0, hit_times)
        self.assertGreaterEqual(
            max(float(hit.score) for hit in hits if float(hit.start_sec) == 2.0),
            0.99,
        )

    def test_expand_neighbor_rerank_candidates_keeps_neighbor_frames(self):
        class DummyIndex:
            def reconstruct(self, idx):
                vectors = {
                    0: np.array([1.0, 0.0], dtype=np.float32),
                    1: np.array([0.9, 0.1], dtype=np.float32),
                    2: np.array([0.2, 0.8], dtype=np.float32),
                }
                return vectors[int(idx)]

        results = [SearchHit(0.0, 0.0, 0.8, "a.mp4")]
        frame_ids = [0]
        query_vector = np.array([[1.0, 0.0]], dtype=np.float32)
        timestamps = np.array([0.0, 1.0, 2.0], dtype=np.float32)
        paths = np.array(["a.mp4", "a.mp4", "a.mp4"], dtype=object)
        config = {
            "frame_neighbor_rerank_enabled": True,
            "frame_neighbor_rerank_top_n": 5,
            "frame_neighbor_rerank_window": 2,
            "fps": 1.0,
        }
        expanded = search_service._expand_neighbor_rerank_candidates(
            results,
            frame_ids,
            query_vector,
            DummyIndex(),
            timestamps,
            paths,
            config,
            precise_image=False,
            seed_top_n=1,
        )
        self.assertGreaterEqual(len(expanded), 2)
        self.assertAlmostEqual(float(expanded[0].score), 1.0)
        self.assertAlmostEqual(float(expanded[0].start_sec), 0.0)


if __name__ == "__main__":
    unittest.main()
