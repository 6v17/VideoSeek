import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.services import indexing_service, search_service


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


if __name__ == "__main__":
    unittest.main()
