import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.services import model_service
from src.services import indexing_service, search_service
from src.services import link_search_service
from src.services import library_service, remote_library_service
from src import utils


class IndexingServiceTests(unittest.TestCase):
    def test_cleanup_missing_library_files_removes_deleted_entries(self):
        meta = {
            "libraries": {
                "C:\\videos": {
                    "files": {
                        "keep.mp4": {"vid": "keep"},
                        "missing.mp4": {"vid": "gone"},
                    }
                }
            }
        }

        with patch("src.services.indexing_service.os.path.exists", side_effect=lambda path: path.endswith("keep.mp4")):
            removed = list(indexing_service.cleanup_missing_library_files(meta, {}, None))

        self.assertEqual(removed, ["gone"])
        self.assertIn("keep.mp4", meta["libraries"]["C:\\videos"]["files"])
        self.assertNotIn("missing.mp4", meta["libraries"]["C:\\videos"]["files"])

    def test_discover_video_files_filters_supported_extensions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "clip.mp4").write_bytes(b"")
            (root / "note.txt").write_text("ignore", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "scene.mkv").write_bytes(b"")

            result = indexing_service.discover_video_files(str(root))

        self.assertEqual(
            sorted(Path(path).name for path in result),
            ["clip.mp4", "scene.mkv"],
        )


class SearchServiceTests(unittest.TestCase):
    @patch("src.services.search_service.faiss.normalize_L2")
    @patch("src.services.search_service.get_text_embedding")
    def test_build_query_vector_for_text(self, mock_text_embedding, mock_normalize):
        mock_text_embedding.return_value = np.array([[1.0, 2.0]], dtype=np.float32)

        result = search_service.build_query_vector("cat on sofa", is_text=True)

        self.assertEqual(result.dtype, np.float32)
        mock_normalize.assert_called_once()

    @patch("src.services.search_service.load_search_assets")
    @patch("src.services.search_service.build_query_vector")
    @patch("src.services.search_service.search_vector")
    @patch("src.services.search_service.load_config")
    def test_run_search_returns_empty_when_index_missing(
        self,
        mock_load_config,
        mock_search_vector,
        mock_build_query_vector,
        mock_load_assets,
    ):
        mock_load_config.return_value = {"cross_index_file": "index.faiss", "cross_vector_file": "vectors.npy"}
        mock_load_assets.return_value = (None, None, None)

        result = search_service.run_search("query", is_text=True)

        self.assertEqual(result, [])
        mock_build_query_vector.assert_not_called()
        mock_search_vector.assert_not_called()


class UtilsTests(unittest.TestCase):
    def test_resolve_resource_path_prefers_configured_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured_dir = Path(temp_dir) / "models"
            configured_dir.mkdir()
            target = configured_dir / "clip_text.onnx"
            target.write_bytes(b"model")

            result = utils.resolve_resource_path("models/clip_text.onnx", str(configured_dir))

        self.assertEqual(Path(result), target)

    def test_resolve_resource_path_falls_back_to_packaged_resource(self):
        packaged_path = str(Path("D:/packaged/models/clip_text.onnx"))
        with patch("src.utils.get_resource_path", return_value=packaged_path), patch(
            "src.utils.os.path.exists",
            side_effect=lambda path: path == packaged_path,
        ):
            result = utils.resolve_resource_path("models/clip_text.onnx", "D:/missing-models")

        self.assertEqual(result, packaged_path)

    def test_get_missing_model_files_reports_missing_entries(self):
        with patch("src.utils.get_model_path", side_effect=lambda filename: f"D:/models/{filename}"), patch(
            "src.utils.os.path.exists",
            side_effect=lambda path: path.endswith("clip_text.onnx"),
        ):
            missing, resolved = utils.get_missing_model_files(["clip_visual.onnx", "clip_text.onnx"])

        self.assertEqual(missing, ["clip_visual.onnx"])
        self.assertEqual(resolved["clip_text.onnx"], "D:/models/clip_text.onnx")


class ModelServiceTests(unittest.TestCase):
    def test_normalize_manifest_uses_base_url_for_missing_file_urls(self):
        manifest = model_service._normalize_manifest(
            {
                "version": "v1",
                "base_url": "https://example.com/models/",
                "files": [{"name": "clip_visual.onnx"}],
            },
            "https://example.com/manifest.json",
        )

        self.assertEqual(manifest["version"], "v1")
        self.assertEqual(
            manifest["files"][0]["sources"][0]["url"],
            "https://example.com/models/clip_visual.onnx",
        )

    def test_normalize_manifest_includes_mirrors(self):
        manifest = model_service._normalize_manifest(
            {
                "base_url": "https://primary.example.com/models/",
                "mirrors": [
                    {"label": "cdn", "base_url": "https://cdn.example.com/models/"},
                    "https://mirror.example.com/models/",
                ],
                "files": [{"name": "clip_visual.onnx"}],
            },
            "https://example.com/manifest.json",
        )

        sources = manifest["files"][0]["sources"]
        self.assertEqual(len(sources), 3)
        self.assertEqual(sources[1]["label"], "cdn")
        self.assertEqual(sources[2]["url"], "https://mirror.example.com/models/clip_visual.onnx")

    def test_normalize_manifest_respects_file_sources(self):
        manifest = model_service._normalize_manifest(
            {
                "base_url": "https://primary.example.com/models/",
                "files": [
                    {
                        "name": "clip_visual.onnx",
                        "sources": [
                            {"label": "oss", "base_url": "https://oss.example.com/models/"},
                            {"label": "github", "url": "https://github.com/example/clip_visual.onnx"},
                        ],
                    }
                ],
            },
            "https://example.com/manifest.json",
        )

        sources = manifest["files"][0]["sources"]
        self.assertEqual(sources[0]["url"], "https://oss.example.com/models/clip_visual.onnx")
        self.assertEqual(sources[1]["label"], "github")


class LinkSearchServiceTests(unittest.TestCase):
    def test_normalize_link_input_extracts_url_from_mixed_text(self):
        mixed = "【最近爆火】 https://www.bilibili.com/video/BV1Zk9FBwELs/?share_source=copy_web"
        normalized = link_search_service._normalize_link_input(mixed)
        self.assertEqual(
            normalized,
            "https://www.bilibili.com/video/BV1Zk9FBwELs/?share_source=copy_web",
        )

    def test_search_against_global_index_deduplicates_and_limits(self):
        class DummyIndex:
            ntotal = 4

            @staticmethod
            def search(_vectors, _k):
                distances = np.array([[0.9, 0.8, 0.7], [0.95, 0.6, 0.5]], dtype=np.float32)
                indices = np.array([[0, 1, 2], [0, 3, 1]], dtype=np.int64)
                return distances, indices

        results = link_search_service._search_against_global_index(
            query_vectors=np.zeros((2, 3), dtype=np.float32),
            source_timestamps=[0.0, 1.0],
            search_index=DummyIndex(),
            index_timestamps=[10.0, 20.0, 30.0, 40.0],
            index_paths=["a.mp4", "b.mp4", "c.mp4", "d.mp4"],
            top_k=3,
            per_frame_k=3,
        )

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["video_path"], "a.mp4")
        self.assertAlmostEqual(results[0]["match_time"], 10.0)
        self.assertGreaterEqual(results[0]["score"], results[1]["score"])

    def test_prepare_source_rejects_invalid_mode(self):
        with self.assertRaises(ValueError):
            link_search_service._prepare_source("https://example.com/video", mode="bad")


class LibraryDetailServiceTests(unittest.TestCase):
    @patch("src.services.library_service.os.path.exists")
    @patch("src.services.library_service.list_libraries")
    @patch("src.services.library_service.load_config")
    def test_list_local_vector_details_builds_entries(
        self,
        mock_load_config,
        mock_list_libraries,
        mock_exists,
    ):
        mock_load_config.return_value = {
            "vector_dir": "data/vector",
            "index_dir": "data/index",
        }
        mock_list_libraries.return_value = {
            "D:/videos": {
                "files": {
                    "a.mp4": {"vid": "vid_a"},
                    "b.mp4": {"vid": "vid_b"},
                }
            }
        }
        mock_exists.side_effect = lambda path: path.endswith("vid_a_vectors.npy") or path.endswith("vid_a_index.faiss")

        result = library_service.list_local_vector_details()

        self.assertEqual(result["total_entries"], 2)
        self.assertEqual(result["entries"][0]["video_rel_path"], "a.mp4")
        self.assertTrue(result["entries"][0]["vector_exists"])
        self.assertFalse(result["entries"][1]["vector_exists"])


class RemoteLibraryDetailServiceTests(unittest.TestCase):
    @patch("src.services.remote_library_service._load_existing_payload")
    @patch("src.services.remote_library_service.os.path.exists", return_value=True)
    @patch("src.services.remote_library_service.get_remote_library_status")
    def test_list_remote_link_details_groups_by_source(
        self,
        mock_status,
        _mock_exists,
        mock_payload,
    ):
        mock_status.return_value = {
            "ready": True,
            "index_file": "data/remote/remote_index.faiss",
            "vector_file": "data/remote/remote_vectors.npy",
        }
        mock_payload.return_value = {
            "source_links": ["https://a", "https://a", "https://b"],
            "titles": ["A", "A", "B"],
            "paths": ["id_a", "id_a", "id_b"],
            "timestamps": [1.0, 2.5, 0.5],
        }

        result = remote_library_service.list_remote_link_details()

        self.assertEqual(result["total_vectors"], 3)
        self.assertEqual(result["total_links"], 2)
        first = result["entries"][0]
        self.assertEqual(first["source_link"], "https://a")
        self.assertEqual(first["frames"], 2)
        self.assertAlmostEqual(first["min_time"], 1.0)
        self.assertAlmostEqual(first["max_time"], 2.5)

if __name__ == "__main__":
    unittest.main()
