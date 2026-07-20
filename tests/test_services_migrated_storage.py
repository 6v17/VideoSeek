import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tests.services_test_support  # noqa: F401 - cv2/faiss stubs
from src.workflows import update_video


class MigratedStorageWorkflowTests(unittest.TestCase):
    def test_delete_physical_video_data_uses_current_config_storage_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            migrated_root = Path(temp_dir) / "migrated-root" / "data"
            vector_dir = migrated_root / "vector"
            index_dir = migrated_root / "index"
            vector_dir.mkdir(parents=True)
            index_dir.mkdir(parents=True)

            vector_file = vector_dir / "vid_a_vectors.npy"
            index_file = index_dir / "vid_a_index.faiss"
            vector_file.write_bytes(b"vector")
            index_file.write_bytes(b"index")

            config = {
                "vector_dir": str(vector_dir),
                "index_dir": str(index_dir),
            }

            with patch(
                "src.workflows.update_video.get_local_model_asset_dirs",
                return_value={"vector_dir": str(vector_dir), "index_dir": str(index_dir)},
            ):
                update_video.delete_physical_video_data("vid_a", config)

            self.assertFalse(vector_file.exists())
            self.assertFalse(index_file.exists())




if __name__ == "__main__":
    unittest.main()
