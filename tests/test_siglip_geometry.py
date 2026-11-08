import os
import types
import unittest
from unittest import mock

import numpy as np

os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")

from src.core.siglip_provider import SigLIP2OnnxEngine
from src.core.vision_preprocess import resize_center_crop_rgb, resize_stretch_rgb


def _preprocess(img_bgr, size=224):
    out = np.empty((3, size, size), dtype=np.float32)
    fake = types.SimpleNamespace(image_size=size)
    SigLIP2OnnxEngine.preprocess_into(fake, img_bgr, out)
    return out


class Siglip2GeometryTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.wide = rng.integers(0, 255, (360, 640, 3), dtype=np.uint8)

    def test_center_crop_mode_matches_precropped_frame(self):
        rgb = np.ascontiguousarray(self.wide[:, :, ::-1])
        pre = np.ascontiguousarray(resize_center_crop_rgb(rgb, 224)[:, :, ::-1])
        with mock.patch(
            "src.services.embedding_preprocess.resolve_embedding_preprocess",
            return_value="center_crop",
        ):
            from_raw = _preprocess(self.wide)
            from_pre = _preprocess(pre)
        np.testing.assert_allclose(from_raw, from_pre, atol=1e-5)

    def test_stretch_mode_matches_precropped_frame(self):
        rgb = np.ascontiguousarray(self.wide[:, :, ::-1])
        pre = np.ascontiguousarray(resize_stretch_rgb(rgb, 224)[:, :, ::-1])
        with mock.patch(
            "src.services.embedding_preprocess.resolve_embedding_preprocess",
            return_value="stretch",
        ):
            from_raw = _preprocess(self.wide)
            from_pre = _preprocess(pre)
        np.testing.assert_allclose(from_raw, from_pre, atol=1e-5)


if __name__ == "__main__":
    unittest.main()
