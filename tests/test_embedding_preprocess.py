import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tests.services_test_support  # noqa: F401
from src.core.vision_preprocess import PREPROCESS_CENTER_CROP, PREPROCESS_STRETCH
from src.services import embedding_preprocess as ep
from src.storage.profile_library_store import ensure_profile_library_db


def _profile_config(provider: str) -> dict:
    return {
        "schema_version": 2,
        "models": {
            "active_profile": "p",
            "profiles": [
                {
                    "id": "p",
                    "provider": provider,
                    "runtime": {"model_variant": "unit"},
                }
            ],
        },
    }


class EmbeddingPreprocessLockTests(unittest.TestCase):
    def test_empty_openai_profile_locks_center_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = str(Path(tmp) / "profile")
            ensure_profile_library_db(base, migrate=False)
            config = _profile_config("clip_onnx")
            with patch.object(ep, "profile_has_visual_assets", return_value=False), patch(
                "src.storage.config_store.get_local_model_asset_dirs",
                return_value={"base_dir": base},
            ):
                mode = ep.resolve_embedding_preprocess(config)
                self.assertEqual(mode, PREPROCESS_CENTER_CROP)
                self.assertEqual(ep.get_locked_embedding_preprocess(base), PREPROCESS_CENTER_CROP)

    def test_empty_chinese_and_siglip_profiles_lock_stretch(self):
        for provider in ("chinese_clip_onnx", "siglip2_onnx"):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as tmp:
                base = str(Path(tmp) / "profile")
                ensure_profile_library_db(base, migrate=False)
                config = _profile_config(provider)
                with patch.object(ep, "profile_has_visual_assets", return_value=False), patch(
                    "src.storage.config_store.get_local_model_asset_dirs",
                    return_value={"base_dir": base},
                ):
                    mode = ep.resolve_embedding_preprocess(config)
                    self.assertEqual(mode, PREPROCESS_STRETCH)
                    self.assertEqual(ep.get_locked_embedding_preprocess(base), PREPROCESS_STRETCH)

    def test_existing_lock_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = str(Path(tmp) / "profile")
            ensure_profile_library_db(base, migrate=False)
            ep.set_locked_embedding_preprocess(base, PREPROCESS_CENTER_CROP)
            config = _profile_config("chinese_clip_onnx")
            with patch.object(ep, "profile_has_visual_assets", return_value=False), patch(
                "src.storage.config_store.get_local_model_asset_dirs",
                return_value={"base_dir": base},
            ):
                self.assertEqual(ep.resolve_embedding_preprocess(config), PREPROCESS_CENTER_CROP)

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

    def test_failed_asset_probe_does_not_lock_center_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = str(Path(tmp) / "profile")
            ensure_profile_library_db(base, migrate=False)
            with patch.object(ep, "profile_has_visual_assets", return_value=None), patch(
                "src.storage.config_store.get_local_model_asset_dirs",
                return_value={"base_dir": base},
            ), patch("src.storage.config_store.load_config", return_value={}):
                mode = ep.resolve_embedding_preprocess({})
                self.assertEqual(mode, PREPROCESS_STRETCH)
                self.assertEqual(ep.get_locked_embedding_preprocess(base), "")


if __name__ == "__main__":
    unittest.main()
