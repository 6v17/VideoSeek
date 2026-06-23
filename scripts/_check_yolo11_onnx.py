"""Temporary script to validate exported YOLO11 ONNX model."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort

MODEL_PATH = Path(r"C:\Users\LiuWei\Desktop\yolov11n\yolo11n.onnx")


def main() -> None:
    print("File:", MODEL_PATH)
    print("Exists:", MODEL_PATH.exists())
    print("Size MB:", round(MODEL_PATH.stat().st_size / 1024 / 1024, 2))

    try:
        import onnx

        model = onnx.load(str(MODEL_PATH))
        onnx.checker.check_model(model)
        print("\nONNX checker: OK")
        print("IR version:", model.ir_version)
        print(
            "Opset imports:",
            [(op.domain or "ai.onnx", op.version) for op in model.opset_import],
        )
        print("Producer:", model.producer_name, model.producer_version)
        print("Graph nodes:", len(model.graph.node))
        print("Graph inputs:", [i.name for i in model.graph.input])
        print("Graph outputs:", [o.name for o in model.graph.output])
    except Exception as exc:
        print("\nONNX checker error:", exc)

    sess = ort.InferenceSession(str(MODEL_PATH), providers=["CPUExecutionProvider"])
    print("\n=== ORT Inputs ===")
    for item in sess.get_inputs():
        print(f"  name={item.name!r} shape={item.shape} type={item.type}")

    print("\n=== ORT Outputs ===")
    for item in sess.get_outputs():
        print(f"  name={item.name!r} shape={item.shape} type={item.type}")

    inp = sess.get_inputs()[0]
    shape = []
    for dim in inp.shape:
        if isinstance(dim, str) or dim is None or int(dim) <= 0:
            shape.append(1)
        else:
            shape.append(int(dim))
    if len(shape) == 4 and shape[1] == 3:
        dummy = np.random.rand(*shape).astype(np.float32)
    else:
        dummy = np.random.rand(1, 3, 640, 640).astype(np.float32)

    print("\n=== Test inference ===")
    print("dummy shape:", dummy.shape)
    outputs = sess.run(None, {inp.name: dummy})
    for idx, out in enumerate(outputs):
        print(
            f"  output[{idx}] shape={out.shape} dtype={out.dtype} "
            f"min={out.min():.4f} max={out.max():.4f}"
        )

    if len(outputs) == 1 and outputs[0].ndim == 3:
        _, channels, anchors = outputs[0].shape
        print("\n=== Detection head analysis ===")
        print(f"  channels={channels}, anchors={anchors}")
        if channels == 84:
            print("  Format: likely YOLOv8/v11 end2end [1, 4+80, N] (COCO 80 classes)")
        elif channels == 85:
            print("  Format: legacy YOLO [1, 5+80, N] with objectness")
        else:
            print("  Format: unexpected channel count for COCO detection")


if __name__ == "__main__":
    main()
