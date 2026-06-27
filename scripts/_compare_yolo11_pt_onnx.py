"""Compare YOLO11 pt vs exported ONNX using ultralytics."""
from __future__ import annotations

from pathlib import Path

import numpy as np

PT_PATH = Path(r"C:\Users\LiuWei\Desktop\yolo11n.pt")
ONNX_PATH = Path(r"C:\Users\LiuWei\Desktop\yolov11n\yolo11n.onnx")


def main() -> None:
    from ultralytics import YOLO

    print("PT:", PT_PATH, "exists=", PT_PATH.exists())
    print("ONNX:", ONNX_PATH, "exists=", ONNX_PATH.exists())

    pt_model = YOLO(str(PT_PATH))
    onnx_model = YOLO(str(ONNX_PATH))

    print("\nPT task/model:", pt_model.task, getattr(pt_model.model, "names", None) and len(pt_model.model.names))
    print("ONNX task/model:", onnx_model.task, getattr(onnx_model.model, "names", None) and len(onnx_model.model.names))

    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, size=(640, 640, 3), dtype=np.uint8)

    pt_res = pt_model.predict(img, verbose=False)[0]
    onnx_res = onnx_model.predict(img, verbose=False)[0]

    print("\nPT boxes:", len(pt_res.boxes))
    print("ONNX boxes:", len(onnx_res.boxes))

    if len(pt_res.boxes) and len(onnx_res.boxes):
        print("PT top conf:", float(pt_res.boxes.conf.max()))
        print("ONNX top conf:", float(onnx_res.boxes.conf.max()))

    # Re-export recommendation check
    print("\nRecommended export flags for VideoSeek:")
    print("  imgsz=640, opset=12, simplify=True, dynamic=False")
    print("  Expected ONNX I/O: images [1,3,640,640] -> output0 [1,84,8400]")


if __name__ == "__main__":
    main()
