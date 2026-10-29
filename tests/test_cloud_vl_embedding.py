import json
import unittest
from unittest.mock import patch

import numpy as np

from src.core.cloud_vl_embedding import (
    CLOUD_VL_PROFILE_ID,
    embed_contents,
    normalize_cloud_vl_settings,
    resolve_cloud_vl_api_key,
)
from src.services.cloud_vl_profile import sync_cloud_vl_profile
from src.services.model_package_service import _profile_files_ready
from src.services.model_service import get_required_model_files


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class CloudVlEmbeddingTests(unittest.TestCase):
    def test_normalize_rejects_unknown_dimension(self):
        settings = normalize_cloud_vl_settings({"enabled": 1, "dimension": 999, "api_key": " sk "})
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["dimension"], 2048)
        self.assertEqual(settings["api_key"], "sk")
        self.assertEqual(settings["model"], "qwen3-vl-embedding")

    def test_api_key_falls_back_to_dashscope_vision_key(self):
        config = {
            "cloud_vl_embedding": {"api_key": ""},
            "understanding": {"remote_vlm": {"api_keys": {"dashscope": "dash-key"}, "provider_preset": "lm_studio"}},
        }
        self.assertEqual(resolve_cloud_vl_api_key(config), "dash-key")
        self.assertEqual(resolve_cloud_vl_api_key({"cloud_vl_embedding": {"api_key": "own"}}), "own")

    def test_enabling_becomes_the_active_model(self):
        config = {
            "models": {
                "active_profile": "chinese_clip_vit_base_patch16",
                "profiles": [{"id": "chinese_clip_vit_base_patch16", "provider": "chinese_clip_onnx"}],
            },
            "cloud_vl_embedding": {"enabled": True, "dimension": 1024},
        }
        sync_cloud_vl_profile(config)
        ids = [item["id"] for item in config["models"]["profiles"]]
        self.assertEqual(config["models"]["active_profile"], CLOUD_VL_PROFILE_ID)
        self.assertEqual(config["cloud_vl_embedding"]["previous_profile_id"], "chinese_clip_vit_base_patch16")
        self.assertIn(CLOUD_VL_PROFILE_ID, ids)
        cloud = next(item for item in config["models"]["profiles"] if item["id"] == CLOUD_VL_PROFILE_ID)
        self.assertEqual(cloud["runtime"]["embedding_dimension"], 1024)
        self.assertEqual(cloud["runtime"]["model_variant"], "qwen3-vl-embedding-1024")
        self.assertTrue(_profile_files_ready(cloud))
        self.assertEqual(
            get_required_model_files(
                {
                    "schema_version": 2,
                    "models": {"active_profile": CLOUD_VL_PROFILE_ID, "profiles": [cloud]},
                }
            ),
            [],
        )

    def test_disabling_removes_profile_and_releases_active(self):
        config = {
            "models": {
                "active_profile": CLOUD_VL_PROFILE_ID,
                "profiles": [
                    {"id": "chinese_clip_vit_base_patch16", "provider": "chinese_clip_onnx"},
                    {"id": CLOUD_VL_PROFILE_ID, "provider": "qwen3_vl_embedding_cloud"},
                ],
            },
            "cloud_vl_embedding": {
                "enabled": False,
                "previous_profile_id": "chinese_clip_vit_base_patch16",
            },
        }
        sync_cloud_vl_profile(config)
        ids = [item["id"] for item in config["models"]["profiles"]]
        self.assertNotIn(CLOUD_VL_PROFILE_ID, ids)
        self.assertEqual(config["models"]["active_profile"], "chinese_clip_vit_base_patch16")

    def test_embed_contents_normalizes_and_batches_by_caller(self):
        calls = []

        def fake_urlopen(request, timeout=0):
            body = json.loads(request.data.decode("utf-8"))
            calls.append(body)
            dim = body["parameters"]["dimension"]
            rows = []
            for index, _item in enumerate(body["input"]["contents"]):
                vector = [0.0] * dim
                vector[index] = 1.0
                rows.append({"index": index, "embedding": vector, "type": "image"})
            return _Body({"output": {"embeddings": rows}})

        settings = normalize_cloud_vl_settings({"dimension": 256})
        with patch("src.core.cloud_vl_embedding.urllib.request.urlopen", fake_urlopen):
            vectors = embed_contents(settings, "sk-test", [{"text": "雾"}, {"image": "data:image/jpeg;base64,aa"}])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], "qwen3-vl-embedding")
        self.assertNotIn("enable_fusion", calls[0]["parameters"])
        self.assertEqual(vectors.shape, (2, 256))
        norms = np.linalg.norm(vectors, axis=1)
        self.assertTrue(np.allclose(norms, 1.0))
        self.assertFalse(np.allclose(vectors[0], vectors[1]))

    def test_runtime_status_reads_cloud_engine(self):
        from src.core import clip_embedding
        from src.core.cloud_vl_embedding import CloudVlEmbeddingEngine

        cloud_engine = CloudVlEmbeddingEngine.__new__(CloudVlEmbeddingEngine)
        previous = clip_embedding.engine
        clip_embedding.engine = cloud_engine
        try:
            status = clip_embedding.get_engine_runtime_status()
        finally:
            clip_embedding.engine = previous
        self.assertTrue(status["initialized"])
        self.assertFalse(status["prefer_gpu"])
        self.assertEqual(status["backend"], "Cloud")
        self.assertEqual(status["warning"], "")


if __name__ == "__main__":
    unittest.main()
