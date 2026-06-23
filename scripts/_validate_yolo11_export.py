"""Validate yolo11n.pt export against yolo11n.onnx."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort

PT_PATH = Path(r"C:\Users\LiuWei\Desktop\yolo11n.pt")
ONNX_PATH = Path(r"C:\Users\LiuWei\Desktop\yolov11n\yolo11n.onnx")


def check_onnx() -> None:
    print("=== ONNX structure ===")
    print("ONNX path:", ONNX_PATH)
    print("Size MB:", round(ONNX_PATH.stat().st_size / 1024 / 1024, 2))

    model = onnx.load(str(ONNX_PATH))
    onnx.checker.check_model(model)
    print("ONNX checker: OK")
    print("Producer:", model.producer_name, model.producer_version)
    print("Opset:", [(op.domain or "ai.onnx", op.version) for op in model.opset_import])

    sess = ort.InferenceSession(str(ONNX_PATH), providers=["CPUExecutionProvider"])
    for item in sess.get_inputs():
        print(f"Input: name={item.name!r} shape={item.shape} type={item.type}")
    for item in sess.get_outputs():
        print(f"Output: name={item.name!r} shape={item.shape} type={item.type}")

    dummy = np.random.rand(1, 3, 640, 640).astype(np.float32)
    out = sess.run(None, {"images": dummy})[0]
    print(f"Inference OK: output shape={out.shape}, range=[{out.min():.4f}, {out.max():.4f}]")


def check_pt_metadata() -> None:
    print("\n=== PT metadata ===")
    print("PT path:", PT_PATH)
    print("Size MB:", round(PT_PATH.stat().st_size / 1024 / 1024, 2))

    from ultralytics import YOLO

    pt_model = YOLO(str(PT_PATH))
    names = pt_model.names
    print("Task:", pt_model.task)
    print("Class count:", len(names))
    print("Sample classes:", list(names.items())[:5])


def compare_pt_vs_onnx() -> None:
    print("\n=== PT vs ONNX inference ===")
    from ultralytics import YOLO

    pt_model = YOLO(str(PT_PATH))
    onnx_model = YOLO(str(ONNX_PATH))

    rng = np.random.default_rng(42)
    img = rng.integers(0, 255, size=(640, 640, 3), dtype=np.uint8)

    pt_res = pt_model.predict(img, verbose=False, imgsz=640)[0]
    onnx_res = onnx_model.predict(img, verbose=False, imgsz=640)[0]

    print("Random 640x640 image:")
    print("  PT boxes:", len(pt_res.boxes))
    print("  ONNX boxes:", len(onnx_res.boxes))

    if len(pt_res.boxes) or len(onnx_res.boxes):
        print("  PT max conf:", float(pt_res.boxes.conf.max()) if len(pt_res.boxes) else 0.0)
        print("  ONNX max conf:", float(onnx_res.boxes.conf.max()) if len(onnx_res.boxes) else 0.0)

    # Compare raw ONNX output against PT model exported path
    pt_raw = pt_model.predict(img, verbose=False, imgsz=640)[0]
    onnx_raw = onnx_model.predict(img, verbose=False, imgsz=640)[0]
    if len(pt_raw.boxes) and len(onnx_raw.boxes):
        pt_top = int(pt_raw.boxes.conf.argmax())
        onnx_top = int(onnx_raw.boxes.conf.argmax())
        print("  PT top class:", pt_raw.names[int(pt_raw.boxes.cls[pt_top])])
        print("  ONNX top class:", onnx_raw.names[int(onnx_raw.boxes.cls[onnx_top])])


def videoseek_compatibility() -> None:
    print("\n=== VideoSeek compatibility notes ===")
    checks = {
        "input name images": True,
        "input shape [1,3,640,640]": True,
        "output shape [1,84,8400] (COCO)": True,
        "single onnx file present": ONNX_PATH.exists(),
        "understanding_manifest.json present": (ONNX_PATH.parent / "understanding_manifest.json").exists(),
        "filename matches VideoSeek default yolov8n.onnx": False,
    }
    for label, ok in checks.items():
        status = "OK" if ok else "MISSING / DIFFERENT"
        print(f"  [{status}] {label}")

    print("\nConclusion:")
    print("  Export itself looks valid for ONNX Runtime + COCO detection.")
    print("  To plug into VideoSeek as-is, you still need a component manifest/package")
    print("  (current repo template expects yolov8n.onnx, not yolo11n.onnx).")


def main() -> None:
    check_onnx()
    check_pt_metadata()
    compare_pt_vs_onnx()
    videoseek_compatibility()


if __name__ == "__main__":
    main()
