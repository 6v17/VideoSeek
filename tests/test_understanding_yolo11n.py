import os
import unittest

import numpy as np

from src.core.understanding.components.yolo11n import decode_yolo_ultralytics_output, nms_xyxy


class Yolo11nDecodeTests(unittest.TestCase):
    def test_nms_keeps_best_non_overlapping_boxes(self):
        boxes = np.array(
            [
                [0.1, 0.1, 0.4, 0.4],
                [0.12, 0.12, 0.42, 0.42],
                [0.6, 0.6, 0.9, 0.9],
            ],
            dtype=np.float32,
        )
        scores = np.array([0.9, 0.8, 0.85], dtype=np.float32)
        keep = nms_xyxy(boxes, scores, iou_threshold=0.5)
        self.assertEqual(keep, [0, 2])

    def test_decode_filters_by_confidence_and_returns_normalized_bbox(self):
        raw = np.zeros((3, 84), dtype=np.float32)
        raw[0, :4] = [320, 320, 200, 200]
        raw[0, 4] = 0.95
        raw[1, :4] = [100, 100, 50, 50]
        raw[1, 5] = 0.10
        raw[2, :4] = [500, 500, 80, 80]
        raw[2, 6] = 0.05

        objects = decode_yolo_ultralytics_output(
            raw,
            input_size=640,
            confidence_threshold=0.25,
            iou_threshold=0.45,
            class_names=("person", "bicycle", "car"),
        )

        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["label"], "person")
        self.assertAlmostEqual(objects[0]["confidence"], 0.95)
        self.assertEqual(len(objects[0]["bbox"]), 4)
        for value in objects[0]["bbox"]:
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)


def _default_model_root() -> str:
    from src.app.config import load_config

    return str(load_config().get("model_dir", "") or os.environ.get("VIDEOSEEK_TEST_MODEL_DIR", "")).strip()


def _models_available() -> bool:
    model_root = _default_model_root()
    if not model_root:
        return False
    yolo_model = os.path.join(
        model_root,
        "understanding",
        "components",
        "vision",
        "object_detection",
        "yolo11n",
        "yolo11n.onnx",
    )
    return os.path.isfile(yolo_model)


@unittest.skipUnless(_models_available(), "installed understanding models not found")
class Yolo11nIntegrationTests(unittest.TestCase):
    def test_infer_returns_objects_list(self):
        from src.core.understanding.registry import infer_installed_component

        image = np.zeros((360, 640, 3), dtype=np.uint8)
        image[80:280, 180:460] = (0, 128, 255)

        result = infer_installed_component("vision/object_detection/yolo11n", image)

        self.assertIn("objects", result)
        self.assertIsInstance(result["objects"], list)
        for item in result["objects"]:
            self.assertIn("label", item)
            self.assertIn("confidence", item)
            self.assertIn("bbox", item)
            self.assertEqual(len(item["bbox"]), 4)


if __name__ == "__main__":
    unittest.main()
