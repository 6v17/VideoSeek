import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import importlib.util
import types

try:
    import cv2 as _real_cv2
    sys.modules["cv2"] = _real_cv2
except ImportError:
    sys.modules.setdefault("cv2", types.SimpleNamespace())
try:
    import onnxruntime as _real_ort
    sys.modules["onnxruntime"] = _real_ort
except ImportError:
    sys.modules.setdefault("onnxruntime", types.SimpleNamespace())
try:
    import faiss as _real_faiss
    sys.modules["faiss"] = _real_faiss
except ImportError:
    _faiss = types.SimpleNamespace()
    _faiss.normalize_L2 = lambda vector: None
    sys.modules["faiss"] = _faiss

from src.services import search_preset_query as preset_query_module
from src.services import search_preset_service as preset_service


class SearchPresetServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = {
            "data_root": self._tmp.name,
            "models": {
                "active_profile": "clip_test",
                "profiles": [
                    {
                        "id": "clip_test",
                        "provider": "clip_onnx",
                        "runtime": {"model_dir": os.path.join(self._tmp.name, "models"), "model_variant": "vit-base-patch32"},
                    },
                    {
                        "id": "siglip_test",
                        "provider": "clip_onnx",
                        "runtime": {"model_dir": os.path.join(self._tmp.name, "models"), "model_variant": "vit-base-patch32"},
                    },
                ],
            },
        }
        self.embedding_patcher = patch.object(
            preset_query_module,
            "encode_preset_query_vector",
            return_value=np.array([[0.1, 0.2, 0.3]], dtype=np.float32),
        )
        self.embedding_patcher.start()

    def tearDown(self):
        self.embedding_patcher.stop()
        self._tmp.cleanup()

    @patch("src.services.search_preset_storage.load_config")
    @patch("src.services.search_preset_query.get_active_embedding_spec")
    @patch("src.services.search_preset_storage.get_active_model_profile")
    @patch("src.services.search_preset_storage.get_configured_data_root")
    def test_text_only_preset_crud_and_cache(
        self,
        mock_data_root,
        mock_profile,
        mock_embedding_spec,
        mock_load_config,
    ):
        mock_data_root.return_value = self._tmp.name
        mock_load_config.return_value = self.config
        mock_profile.return_value = self.config["models"]["profiles"][0]
        mock_embedding_spec.return_value = {
            "model_id": "clip_test",
            "provider": "clip_onnx",
            "embedding_space": "clip_test",
            "dimension": 3,
            "metric": "ip",
        }

        created = preset_service.create_preset(
            name="Anime Night",
            query="anime night city",
            config=self.config,
        )
        self.assertEqual(created["type"], "mixed")
        self.assertEqual(created["query"], "anime night city")
        self.assertEqual(created["ref_files"], [])
        presets = preset_service.list_presets(config=self.config)
        self.assertEqual(len(presets), 1 + len(preset_service.BUILTIN_SEARCH_PRESETS))

        plan = preset_service.build_preset_search_plan(created["id"], config=self.config)
        self.assertEqual(plan["query_vector"].shape, (1, 3))
        cache_path = preset_service._query_cache_path(created["id"], config=self.config)
        self.assertTrue(os.path.isfile(cache_path))
        self.assertIn("clip_test", cache_path.replace("\\", "/"))

        updated = preset_service.update_preset(
            created["id"],
            name="Night City",
            query="anime night skyline",
            config=self.config,
        )
        self.assertEqual(updated["name"], "Night City")

        self.assertTrue(preset_service.delete_preset(created["id"], config=self.config))
        remaining = preset_service.list_presets(config=self.config)
        self.assertEqual(len(remaining), len(preset_service.BUILTIN_SEARCH_PRESETS))
        self.assertNotIn(created["id"], {item["id"] for item in remaining})

    @patch("src.services.search_preset_storage.load_config")
    @patch("src.services.search_preset_query.get_active_embedding_spec")
    @patch("src.services.search_preset_storage.get_active_model_profile")
    @patch("src.services.search_preset_storage.get_configured_data_root")
    def test_image_preset_copies_reference_and_builds_cache(
        self,
        mock_data_root,
        mock_profile,
        mock_embedding_spec,
        mock_load_config,
    ):
        mock_data_root.return_value = self._tmp.name
        mock_load_config.return_value = self.config
        mock_profile.return_value = self.config["models"]["profiles"][0]
        mock_embedding_spec.return_value = {
            "model_id": "clip_test",
            "provider": "clip_onnx",
            "embedding_space": "clip_test",
            "dimension": 3,
            "metric": "ip",
        }
        source_image = os.path.join(self._tmp.name, "ref.png")
        with open(source_image, "wb") as handle:
            handle.write(b"fake-image")

        created = preset_service.create_preset(
            name="Blue Tone",
            source_image_paths=[source_image],
            config=self.config,
        )
        ref_path = preset_service.get_preset_ref_path(created, config=self.config)
        self.assertTrue(os.path.isfile(ref_path))
        self.assertIn("search_presets/refs", ref_path.replace("\\", "/"))
        vector = preset_service.resolve_preset_query_vector(created, config=self.config)
        self.assertEqual(vector.shape, (1, 3))

    @patch("src.services.search_preset_storage.load_config")
    @patch("src.services.search_preset_query.get_active_embedding_spec")
    @patch("src.services.search_preset_storage.get_active_model_profile")
    @patch("src.services.search_preset_storage.get_configured_data_root")
    def test_mixed_preset_with_multiple_images(
        self,
        mock_data_root,
        mock_profile,
        mock_embedding_spec,
        mock_load_config,
    ):
        mock_data_root.return_value = self._tmp.name
        mock_load_config.return_value = self.config
        mock_profile.return_value = self.config["models"]["profiles"][0]
        mock_embedding_spec.return_value = {
            "model_id": "clip_test",
            "provider": "clip_onnx",
            "embedding_space": "clip_test",
            "dimension": 3,
            "metric": "ip",
        }
        image_paths = []
        for index in range(2):
            path = os.path.join(self._tmp.name, f"ref_{index}.png")
            with open(path, "wb") as handle:
                handle.write(f"fake-image-{index}".encode("utf-8"))
            image_paths.append(path)

        created = preset_service.create_preset(
            name="Moody Blue",
            query="dark blue close-up",
            source_image_paths=image_paths,
            config=self.config,
        )
        self.assertEqual(len(created["ref_files"]), 2)
        self.assertEqual(preset_service.describe_preset_content(created), "dark blue close-up + [2 image(s)] + (50:50)")

        updated = preset_service.update_preset(
            created["id"],
            fusion={"text_weight": 0.7, "image_weight": 0.3},
            config=self.config,
        )
        self.assertEqual(updated["fusion"]["text_weight"], 0.7)

        updated = preset_service.update_preset(
            created["id"],
            source_image_paths=[image_paths[0]],
            replace_reference_images=True,
            config=self.config,
        )
        self.assertEqual(len(updated["ref_files"]), 1)

    @patch("src.services.search_preset_storage.load_config")
    @patch("src.services.search_preset_storage.get_active_model_profile")
    @patch("src.services.search_preset_storage.get_configured_data_root")
    def test_legacy_text_and_image_presets_normalize_to_mixed(
        self,
        mock_data_root,
        mock_profile,
        mock_load_config,
    ):
        mock_data_root.return_value = self._tmp.name
        mock_load_config.return_value = self.config
        mock_profile.return_value = self.config["models"]["profiles"][0]
        root = preset_service.get_search_preset_root(self.config)
        os.makedirs(root, exist_ok=True)
        refs_dir = preset_service.get_preset_refs_dir(self.config)
        os.makedirs(refs_dir, exist_ok=True)
        legacy_ref = os.path.join(refs_dir, "legacy.png")
        with open(legacy_ref, "wb") as handle:
            handle.write(b"legacy")
        preset_service.save_presets_document(
            {
                "presets": [
                    {"id": "t1", "type": "text", "name": "Old Text", "query": "night city"},
                    {
                        "id": "i1",
                        "type": "image",
                        "name": "Old Image",
                        "ref_file": "refs/legacy.png",
                    },
                ]
            },
            config=self.config,
        )
        presets = preset_service.list_presets(config=self.config)
        self.assertEqual(len(presets), 2 + len(preset_service.BUILTIN_SEARCH_PRESETS))
        self.assertTrue(all(item["type"] == "mixed" for item in presets))
        image_preset = next(item for item in presets if item["name"] == "Old Image")
        self.assertEqual(image_preset["ref_files"], ["refs/legacy.png"])

    @patch("src.services.search_preset_storage.load_config")
    @patch("src.services.search_preset_query.get_active_embedding_spec")
    @patch("src.services.search_preset_storage.get_active_model_profile")
    @patch("src.services.search_preset_storage.get_configured_data_root")
    def test_shared_presets_with_profile_scoped_query_cache(
        self,
        mock_data_root,
        mock_profile,
        mock_embedding_spec,
        mock_load_config,
    ):
        mock_data_root.return_value = self._tmp.name
        mock_load_config.return_value = self.config
        mock_embedding_spec.return_value = {
            "model_id": "clip_test",
            "provider": "clip_onnx",
            "embedding_space": "clip_test",
            "dimension": 3,
            "metric": "ip",
        }

        mock_profile.return_value = self.config["models"]["profiles"][0]
        created = preset_service.create_preset(name="Shared Mood", query="blue night", config=self.config)
        clip_cache = preset_service._query_cache_path(created["id"], config=self.config)

        mock_profile.return_value = self.config["models"]["profiles"][1]
        presets = preset_service.list_presets(config=self.config)
        self.assertEqual(len(presets), 1 + len(preset_service.BUILTIN_SEARCH_PRESETS))
        self.assertEqual(presets[0]["id"], created["id"])
        siglip_cache = preset_service._query_cache_path(created["id"], config=self.config)
        self.assertNotEqual(clip_cache.replace("\\", "/"), siglip_cache.replace("\\", "/"))
        self.assertIn("siglip_test", siglip_cache.replace("\\", "/"))

        preset_service.resolve_preset_query_vector(created, config=self.config, force_refresh=True)
        self.assertTrue(os.path.isfile(clip_cache))
        self.assertTrue(os.path.isfile(siglip_cache))

    @patch("src.services.search_preset_storage.load_config")
    @patch("src.services.search_preset_query.get_active_embedding_spec")
    @patch("src.services.search_preset_storage.get_active_model_profile")
    @patch("src.services.search_preset_storage.get_configured_data_root")
    def test_update_fusion_without_recopying_reference_images(
        self,
        mock_data_root,
        mock_profile,
        mock_embedding_spec,
        mock_load_config,
    ):
        mock_data_root.return_value = self._tmp.name
        mock_load_config.return_value = self.config
        mock_profile.return_value = self.config["models"]["profiles"][0]
        mock_embedding_spec.return_value = {
            "model_id": "clip_test",
            "provider": "clip_onnx",
            "embedding_space": "clip_test",
            "dimension": 3,
            "metric": "ip",
        }
        source_image = os.path.join(self._tmp.name, "ref.png")
        with open(source_image, "wb") as handle:
            handle.write(b"fake-image")

        created = preset_service.create_preset(
            name="Mixed",
            query="blue night",
            source_image_paths=[source_image],
            config=self.config,
        )
        ref_path = preset_service.get_preset_ref_path(created, config=self.config)
        self.assertTrue(os.path.isfile(ref_path))

        updated = preset_service.update_preset(
            created["id"],
            fusion={"text_weight": 0.8, "image_weight": 0.2},
            source_image_paths=[ref_path],
            replace_reference_images=True,
            config=self.config,
        )
        self.assertEqual(updated["fusion"]["text_weight"], 0.8)
        self.assertTrue(os.path.isfile(ref_path))

    def test_create_preset_requires_text_or_image(self):
        with self.assertRaises(ValueError):
            preset_service.create_preset(name="Empty", query="", source_image_paths=[], config=self.config)

    @patch("src.services.search_preset_storage.load_config")
    @patch("src.services.search_preset_query.get_active_embedding_spec")
    @patch("src.services.search_preset_storage.get_active_model_profile")
    @patch("src.services.search_preset_storage.get_configured_data_root")
    def test_build_preset_search_plan_uses_live_search_mode(
        self,
        mock_data_root,
        mock_profile,
        mock_embedding_spec,
        mock_load_config,
    ):
        mock_data_root.return_value = self._tmp.name
        self.config["search_mode"] = "chunk"
        mock_load_config.return_value = self.config
        mock_profile.return_value = self.config["models"]["profiles"][0]
        mock_embedding_spec.return_value = {
            "model_id": "clip_test",
            "provider": "clip_onnx",
            "embedding_space": "clip_test",
            "dimension": 3,
            "metric": "ip",
        }

        created = preset_service.create_preset(
            name="Frame Saved",
            query="night city",
            mode="frame",
            config=self.config,
        )
        plan = preset_service.build_preset_search_plan(created["id"], config=self.config)
        self.assertEqual(plan["search_mode"], "chunk")

    @patch("src.services.search_preset_storage.load_config")
    @patch("src.services.search_preset_query.get_active_embedding_spec")
    @patch("src.services.search_preset_storage.get_active_model_profile")
    @patch("src.services.search_preset_storage.get_configured_data_root")
    def test_build_preset_search_plan_mixed_uses_ref_for_pixel_query(
        self,
        mock_data_root,
        mock_profile,
        mock_embedding_spec,
        mock_load_config,
    ):
        mock_data_root.return_value = self._tmp.name
        mock_load_config.return_value = self.config
        mock_profile.return_value = self.config["models"]["profiles"][0]
        mock_embedding_spec.return_value = {
            "model_id": "clip_test",
            "provider": "clip_onnx",
            "embedding_space": "clip_test",
            "dimension": 3,
            "metric": "ip",
        }
        source_image = os.path.join(self._tmp.name, "ref.png")
        with open(source_image, "wb") as handle:
            handle.write(b"fake-image")

        created = preset_service.create_preset(
            name="Mixed",
            query="blue night",
            source_image_paths=[source_image],
            config=self.config,
        )
        plan = preset_service.build_preset_search_plan(created["id"], config=self.config)
        self.assertFalse(plan["is_text"])
        self.assertTrue(plan["has_image"])
        self.assertEqual(plan["query_data"], "blue night")
        self.assertTrue(os.path.isfile(plan["pixel_query_data"]))

    @patch("src.services.search_preset_storage.load_config")
    @patch("src.services.search_preset_storage.get_active_model_profile")
    @patch("src.services.search_preset_storage.get_configured_data_root")
    def test_builtin_presets_seeded_once(
        self,
        mock_data_root,
        mock_profile,
        mock_load_config,
    ):
        mock_data_root.return_value = self._tmp.name
        mock_load_config.return_value = self.config
        mock_profile.return_value = self.config["models"]["profiles"][0]

        first = preset_service.list_presets(config=self.config)
        self.assertEqual(len(first), len(preset_service.BUILTIN_SEARCH_PRESETS))
        by_id = {item["id"]: item for item in first}
        self.assertEqual(by_id["builtin_smile"]["name"], "开心")
        self.assertEqual(by_id["builtin_smile"]["query"], "a person with a big smile")
        self.assertEqual(by_id["builtin_landscape"]["query"], "beautiful landscape")

        self.assertEqual(preset_service.ensure_builtin_search_presets(config=self.config), 0)
        self.assertEqual(len(preset_service.list_presets(config=self.config)), len(first))

        preset_service.delete_preset("builtin_smile", config=self.config)
        self.assertEqual(preset_service.ensure_builtin_search_presets(config=self.config), 0)
        ids = {item["id"] for item in preset_service.list_presets(config=self.config)}
        self.assertNotIn("builtin_smile", ids)


if __name__ == "__main__":
    unittest.main()
