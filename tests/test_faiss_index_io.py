import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.modules.setdefault("cv2", object())

from src.core import faiss_index as faiss_index_module


class FaissIndexIoTests(unittest.TestCase):
    def test_path_has_non_ascii_detects_cjk(self):
        self.assertTrue(faiss_index_module._path_has_non_ascii("J:/视频/index.faiss"))
        self.assertFalse(faiss_index_module._path_has_non_ascii("J:/video/index.faiss"))

    @unittest.skipUnless(sys.platform == "win32", "Windows FAISS ASCII staging root")
    def test_resolve_faiss_ascii_staging_root_is_ascii(self):
        with tempfile.TemporaryDirectory() as tmp:
            faiss_index_module._FAISS_STAGING_ROOT = None
            with patch.object(faiss_index_module.os, "makedirs") as makedirs_mock:
                root = faiss_index_module._resolve_faiss_ascii_staging_root()
            self.assertFalse(faiss_index_module._path_has_non_ascii(root))
            self.assertIn("VideoSeek", root)
            self.assertIn("faiss-io", root)
            makedirs_mock.assert_called()
            faiss_index_module._FAISS_STAGING_ROOT = None

    @unittest.skipUnless(sys.platform == "win32", "Windows FAISS ASCII staging cleanup")
    def test_ascii_stage_dir_is_removed_after_use(self):
        faiss_index_module._FAISS_STAGING_ROOT = None
        seen_dirs = []
        with faiss_index_module._faiss_ascii_stage_dir() as stage_dir:
            seen_dirs.append(stage_dir)
            self.assertTrue(os.path.isdir(stage_dir))
            self.assertFalse(faiss_index_module._path_has_non_ascii(stage_dir))
        self.assertFalse(os.path.exists(seen_dirs[0]))
        faiss_index_module._FAISS_STAGING_ROOT = None

    def test_commit_temp_file_uses_copy_when_drives_differ(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_path = os.path.join(tmp, "temp.faiss")
            target_path = os.path.join(tmp, "final.faiss")
            with open(temp_path, "wb") as handle:
                handle.write(b"faiss-stub")

            with (
                patch.object(faiss_index_module, "_paths_on_same_drive", return_value=False),
                patch.object(faiss_index_module.shutil, "copy2") as copy2_mock,
                patch.object(faiss_index_module.os, "replace") as replace_mock,
            ):
                faiss_index_module._commit_temp_file(temp_path, target_path)

            copy2_mock.assert_called_once_with(temp_path, target_path)
            replace_mock.assert_not_called()
            self.assertFalse(os.path.exists(temp_path))

    @unittest.skipUnless(sys.platform == "win32", "Windows FAISS Unicode staging")
    def test_write_and_read_index_under_unicode_directory(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed in this interpreter")
        if getattr(faiss_index_module.faiss, "IndexFlatIP", None) is None:
            self.skipTest("faiss not installed in this interpreter")

        vectors = np.random.randn(8, 8).astype("float32")
        with tempfile.TemporaryDirectory(prefix="vs_faiss_") as tmp:
            root = os.path.join(tmp, "视频库")
            os.makedirs(root, exist_ok=True)
            index_file = os.path.join(root, "sample_index.faiss")
            faiss_index_module.create_clip_index(vectors, index_file)
            self.assertTrue(os.path.isfile(index_file))
            loaded = faiss_index_module.load_clip_index(index_file)
            self.assertIsNotNone(loaded)
            self.assertEqual(int(loaded.ntotal), 8)


if __name__ == "__main__":
    unittest.main()
