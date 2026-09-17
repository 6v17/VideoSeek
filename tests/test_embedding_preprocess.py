import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tests.services_test_support  # noqa: F401
from src.core.vision_preprocess import PREPROCESS_CENTER_CROP, PREPROCESS_STRETCH
from src.services import embedding_preprocess as ep
from src.storage.profile_library_store import ensure_profile_library_db


class EmbeddingPreprocessLockTests(unittest.TestCase):
    def test_empty_profile_locks_center_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = str(Path(tmp) / "profile")
            ensure_profile_library_db(base, migrate=False)
            with patch.object(ep, "profile_has_visual_assets", return_value=False), patch(
                "src.storage.config_store.get_local_model_asset_dirs",
                return_value={"base_dir": base},
            ), patch("src.storage.config_store.load_config", return_value={}):
                mode = ep.resolve_embedding_preprocess({})
                self.assertEqual(mode, PREPROCESS_CENTER_CROP)
                self.assertEqual(ep.get_locked_embedding_preprocess(base), PREPROCESS_CENTER_CROP)
                # second call keeps lock
                self.assertEqual(ep.resolve_embedding_preprocess({}), PREPROCESS_CENTER_CROP)

    def test_existing_assets_lock_stretch(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = str(Path(tmp) / "profile")
            ensure_profile_library_db(base, migrate=False)
            with patch.object(ep, "profile_has_visual_assets", return_value=True), patch(
                "src.storage.config_store.get_local_model_asset_dirs",
                return_value={"base_dir": base},
            ), patch("src.storage.config_store.load_config", return_value={}):
                mode = ep.resolve_embedding_preprocess({})
                self.assertEqual(mode, PREPROCESS_STRETCH)
                # even if assets later empty, lock sticks
                with patch.object(ep, "profile_has_visual_assets", return_value=False):
                    self.assertEqual(ep.resolve_embedding_preprocess({}), PREPROCESS_STRETCH)


if __name__ == "__main__":
    unittest.main()
