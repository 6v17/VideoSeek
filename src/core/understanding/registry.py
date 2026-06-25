from __future__ import annotations

import json
import os
from typing import Any, Callable, Mapping

import numpy as np

from src.core.understanding.base import UnderstandingComponent
from src.core.understanding.coco_labels import resolve_class_names
from src.core.understanding.ort_runtime import run_with_cpu_fallback
from src.services.understanding_paths import get_component_dir

_REGISTRY: dict[str, Callable[..., UnderstandingComponent]] = {}


def register_understanding_component(registry_key: str, factory: Callable[..., UnderstandingComponent]) -> None:
    key = str(registry_key or "").strip()
    if not key:
        raise ValueError("registry_key is required")
    _REGISTRY[key] = factory


def build_understanding_component(
    manifest: Mapping[str, Any],
    *,
    component_dir: str | None = None,
    params: Mapping[str, Any] | None = None,
) -> UnderstandingComponent:
    engine = dict(manifest.get("engine") or {})
    registry_key = str(engine.get("registry_key", "") or "").strip()
    factory = _REGISTRY.get(registry_key)
    if factory is None:
        raise RuntimeError(f"Unsupported understanding component registry_key: {registry_key!r}")

    component_id = str(manifest.get("id", "") or "").strip()
    resolved_dir = str(component_dir or get_component_dir(component_id)).strip()
    delivery = str(manifest.get("delivery", "local") or "local").strip().lower()
    manifest_path = os.path.join(resolved_dir, "understanding_manifest.json")
    if not resolved_dir:
        raise RuntimeError(f"Component directory not found for {component_id!r}")
    if delivery == "remote":
        if not os.path.isfile(manifest_path):
            raise RuntimeError(f"Remote component manifest not found: {manifest_path}")
    elif not os.path.isdir(resolved_dir):
        raise RuntimeError(f"Component directory not found: {resolved_dir}")

    runtime = dict(manifest.get("runtime") or {})
    return factory(manifest, resolved_dir, dict(params or {}), runtime)


def infer_installed_component(
    component_id: str,
    image_bgr: np.ndarray,
    *,
    model_dir: str | None = None,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from src.services.understanding_paths import get_component_manifest_path
    from src.services.understanding_resource_service import validate_component_manifest

    manifest_path = get_component_manifest_path(component_id, model_dir=model_dir)
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    validated = validate_component_manifest(manifest, component_dir=os.path.dirname(manifest_path))
    component = build_understanding_component(validated, component_dir=os.path.dirname(manifest_path), params=params)
    try:
        return component.infer(image_bgr)
    finally:
        component.close()


def _register_builtin_components() -> None:
    from src.core.understanding.components.remote_vl_caption import RemoteVlCaptionComponent
    from src.core.understanding.components.yolo11n import Yolo11nObjectDetectionComponent

    register_understanding_component("vision.object_detection.yolo11n", Yolo11nObjectDetectionComponent)
    register_understanding_component("vision.image_caption.qwen3_vl_remote", RemoteVlCaptionComponent)


_register_builtin_components()
