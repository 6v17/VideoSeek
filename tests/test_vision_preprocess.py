import os
import unittest

import numpy as np

os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")


class VisionPreprocessTests(unittest.TestCase):
    def test_clip_frame_vf_center_crop(self):
        from src.core.vision_preprocess import clip_frame_vf

        self.assertEqual(
            clip_frame_vf(fps=2.0, size=224, preprocess="center_crop"),
            "fps=2.000000,scale=224:224:force_original_aspect_ratio=increase:flags=bicubic,crop=224:224",
        )

    def test_clip_frame_vf_stretch(self):
        from src.core.vision_preprocess import clip_frame_vf

        self.assertEqual(
            clip_frame_vf(fps=2.0, size=224, preprocess="stretch"),
            "fps=2.000000,scale=224:224:flags=bicubic",
        )

    def test_resize_center_crop_keeps_center_content(self):
        from src.core.vision_preprocess import resize_center_crop_rgb

        img = np.zeros((100, 400, 3), dtype=np.uint8)
        img[:, :200] = (255, 0, 0)
        img[:, 200:] = (0, 255, 0)
        out = resize_center_crop_rgb(img, 224)
        self.assertEqual(out.shape, (224, 224, 3))
        center = out[112, 112]
        self.assertGreater(int(center[1]), int(center[0]))

    def test_resize_stretch_distorts_to_square(self):
        from src.core.vision_preprocess import resize_stretch_rgb

        img = np.zeros((100, 400, 3), dtype=np.uint8)
        out = resize_stretch_rgb(img, 224)
        self.assertEqual(out.shape, (224, 224, 3))


if __name__ == "__main__":
    unittest.main()
