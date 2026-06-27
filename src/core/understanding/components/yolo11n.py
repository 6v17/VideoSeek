from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from src.core.understanding.base import UnderstandingComponent, merge_params
from src.core.understanding.coco_labels import resolve_class_names
from src.core.understanding.ort_runtime import run_with_cpu_fallback


def _resolve_model_path(component_dir: str, files_map: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    files_map = dict(files_map or manifest.get("files") or {})
    model_name = str(files_map.get("model", "") or "").strip()
    if not model_name:
        required = list(manifest.get("required_files") or [])
        model_name = str(required[0] if required else "").strip()
    if not model_name:
        raise RuntimeError("Missing model file mapping for object detection component")
    model_path = os.path.join(component_dir, model_name)
    if not os.path.isfile(model_path):
        raise RuntimeError(f"Model file not found: {model_path}")
    return model_path


def _xywh_to_xyxy_normalized(boxes: np.ndarray, input_size: int) -> np.ndarray:
    cx = boxes[:, 0] / input_size
    cy = boxes[:, 1] / input_size
    width = boxes[:, 2] / input_size
    height = boxes[:, 3] / input_size
    x1 = np.clip(cx - width / 2.0, 0.0, 1.0)
    y1 = np.clip(cy - height / 2.0, 0.0, 1.0)
    x2 = np.clip(cx + width / 2.0, 0.0, 1.0)
    y2 = np.clip(cy + height / 2.0, 0.0, 1.0)
    return np.stack([x1, y1, x2, y2], axis=1)


def _box_iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    area_box = max(0.0, (box[2] - box[0])) * max(0.0, (box[3] - box[1]))
    area_boxes = np.maximum(0.0, boxes[:, 2] - boxes[:, 0]) * np.maximum(0.0, boxes[:, 3] - boxes[:, 1])
    union = area_box + area_boxes - inter + 1e-9
    return inter / union


def nms_xyxy(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    if boxes.size == 0:
        return []
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        current = int(order[0])
        keep.append(current)
        if order.size == 1:
            break
        rest = order[1:]
        ious = _box_iou(boxes[current], boxes[rest])
        order = rest[ious <= iou_threshold]
    return keep


def decode_yolo_ultralytics_output(
    raw_output: np.ndarray,
    *,
    input_size: int,
    confidence_threshold: float,
    iou_threshold: float,
    class_names: Sequence[str],
    max_detections: int = 100,
) -> list[dict[str, Any]]:
    if raw_output.ndim != 2:
        raise ValueError(f"Expected 2D detection output, got shape {raw_output.shape}")

    boxes_xywh = raw_output[:, :4]
    class_scores = raw_output[:, 4:]
    if class_scores.size == 0:
        return []

    class_ids = np.argmax(class_scores, axis=1)
    confidences = class_scores[np.arange(class_scores.shape[0]), class_ids]
    mask = confidences >= confidence_threshold
    if not np.any(mask):
        return []

    boxes_xywh = boxes_xywh[mask]
    confidences = confidences[mask]
    class_ids = class_ids[mask]
    boxes_xyxy = _xywh_to_xyxy_normalized(boxes_xywh.astype(np.float32), input_size)

    keep_indices = nms_xyxy(boxes_xyxy, confidences, iou_threshold)
    objects: list[dict[str, Any]] = []
    for index in keep_indices[:max_detections]:
        class_id = int(class_ids[index])
        label = class_names[class_id] if 0 <= class_id < len(class_names) else str(class_id)
        bbox = boxes_xyxy[index]
        objects.append(
            {
                "label": label,
                "confidence": float(confidences[index]),
                "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
            }
        )
    return objects


class Yolo11nObjectDetectionComponent(UnderstandingComponent):
    def __init__(
        self,
        manifest: Mapping[str, Any],
        component_dir: str,
        params: Mapping[str, Any] | None = None,
        runtime: Mapping[str, Any] | None = None,
    ):
        self.component_id = str(manifest.get("id", "") or "").strip()
        self._manifest = dict(manifest)
        self._component_dir = component_dir
        self._params = merge_params(manifest, params)
        self._runtime = dict(runtime or manifest.get("runtime") or {})
        self._model_path = _resolve_model_path(component_dir, dict(manifest.get("files") or {}), manifest)
        self._input_size = int(self._params.get("input_size", 640))
        self._confidence_threshold = float(self._params.get("confidence_threshold", 0.25))
        self._iou_threshold = float(self._params.get("iou_threshold", 0.45))
        self._class_names = resolve_class_names(str(self._params.get("class_names", "coco")))
        self._prefer_gpu = bool(self._runtime.get("prefer_gpu", True))
        self._provider_hints = list(self._runtime.get("provider_hints") or [])

    def infer(self, image_bgr: np.ndarray) -> dict[str, Any]:
        if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
            return {"objects": []}

        blob = self._preprocess(image_bgr)

        def _run(session):
            input_name = session.get_inputs()[0].name
            outputs = session.run(None, {input_name: blob})
            return outputs[0][0].transpose(1, 0)

        raw_output, _using_gpu = run_with_cpu_fallback(
            model_path=self._model_path,
            prefer_gpu=self._prefer_gpu,
            provider_hints=self._provider_hints,
            run_fn=_run,
        )
        objects = decode_yolo_ultralytics_output(
            raw_output,
            input_size=self._input_size,
            confidence_threshold=self._confidence_threshold,
            iou_threshold=self._iou_threshold,
            class_names=self._class_names,
        )
        return {"objects": objects}

    def _preprocess(self, image_bgr: np.ndarray) -> np.ndarray:
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(image_rgb, (self._input_size, self._input_size), interpolation=cv2.INTER_LINEAR)
        blob = resized.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))
        return np.ascontiguousarray(blob[None, ...])
