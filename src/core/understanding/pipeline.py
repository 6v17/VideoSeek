from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

from src.app.logging_utils import get_logger
from src.core.understanding.base import UnderstandingStoppedError
from src.core.understanding.registry import build_understanding_component
from src.services.understanding_paths import get_component_manifest_path
from src.services.understanding_resource_service import is_component_installed, validate_component_manifest

logger = get_logger("understanding.pipeline")

TASK_TO_VISION_KEY = {
    "image_caption": "image_caption",
}


@dataclass(frozen=True)
class PipelineStepResult:
    step: str
    component_id: str
    payload: dict[str, Any]


class UnderstandingPipeline:
    def __init__(
        self,
        profile_manifest: Mapping[str, Any],
        *,
        model_dir: str | None = None,
        config=None,
        output_mode: str | None = None,
    ):
        self.profile_manifest = dict(profile_manifest)
        self.model_dir = str(model_dir or "").strip() or None
        self.config = config
        defaults = dict(self.profile_manifest.get("defaults") or {})
        self.keyframe_strategy = str(defaults.get("keyframe_strategy", "midpoint") or "midpoint")
        self._component_cache: dict[str, Any] = {}
        from src.services.understanding_resource_service import (
            UNDERSTANDING_MODE_TAGS,
            get_remote_vlm_settings,
            normalize_understanding_mode,
        )

        if output_mode:
            self.output_mode = normalize_understanding_mode(output_mode)
        else:
            settings = get_remote_vlm_settings(config)
            self.output_mode = normalize_understanding_mode(
                settings.get("understanding_mode", UNDERSTANDING_MODE_TAGS)
            )

    def close(self) -> None:
        for component in self._component_cache.values():
            try:
                component.close()
            except Exception as exc:
                logger.warning("Failed to close understanding component: %s", exc)
        self._component_cache.clear()

    def enabled_steps(self) -> list[dict[str, Any]]:
        pipeline = self.profile_manifest.get("pipeline")
        if not isinstance(pipeline, list):
            return []
        steps: list[dict[str, Any]] = []
        for item in pipeline:
            if not isinstance(item, dict):
                continue
            if not bool(item.get("enabled", True)):
                continue
            step = str(item.get("step", "") or "").strip()
            component_id = str(item.get("component", "") or "").strip()
            # Legacy profiles may still list object_detection; product path is caption-only.
            if step == "object_detection":
                continue
            if step and component_id:
                steps.append(dict(item))
        return steps

    def component_map(self) -> dict[str, str]:
        return {
            str(step["step"]): str(step["component"])
            for step in self.enabled_steps()
        }

    def run_video_chunks(
        self,
        *,
        video_path: str,
        chunks: list[Mapping[str, Any]],
        should_stop_callback=None,
        chunk_completed_callback=None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        total = len(chunks)
        for chunk_index, chunk in enumerate(chunks):
            if should_stop_callback and should_stop_callback():
                raise UnderstandingStoppedError("Evidence generation stopped by user")
            result = self.run_chunk(
                video_path=video_path,
                chunk=chunk,
                chunk_index=chunk_index,
                should_stop_callback=should_stop_callback,
            )
            results.append(result)
            if chunk_completed_callback:
                chunk_completed_callback(chunk_index, total, result)
        return results

    def _wrap_step_result(self, component_id: str, step_name: str, infer_result: Mapping[str, Any]) -> dict[str, Any]:
        if step_name == "image_caption":
            from src.services.understanding_resource_service import UNDERSTANDING_MODE_TAGS
            from src.services.understanding_tags import format_tags_for_display, parse_vlm_tag_list

            raw_text = str(infer_result.get("text", "") or "").strip()
            if self.output_mode == UNDERSTANDING_MODE_TAGS:
                tags = parse_vlm_tag_list(raw_text)
                display_text = format_tags_for_display(tags) if tags else raw_text
                return {
                    "source": component_id,
                    "text": display_text,
                    "raw_text": raw_text,
                    "tags": tags,
                }
            return {
                "source": component_id,
                "text": raw_text,
                "raw_text": raw_text,
                "tags": [],
            }
        return {"source": component_id, **dict(infer_result)}

    def run_chunk(
        self,
        *,
        video_path: str,
        chunk: Mapping[str, Any],
        chunk_index: int,
        should_stop_callback=None,
    ) -> dict[str, Any]:
        start_sec = float(chunk.get("start", 0.0))
        end_sec = float(chunk.get("end", start_sec))
        timestamp_sec = self._sample_timestamp(start_sec, end_sec)
        from src.media.thumbnail import get_single_thumbnail

        frame_bgr = get_single_thumbnail(video_path, timestamp_sec)
        evidence = {"vision": {}, "audio": {}}
        tags: list[str] = []

        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            logger.warning(
                "Keyframe decode failed for %s at %.3fs (chunk %s)",
                video_path,
                timestamp_sec,
                chunk_index,
            )
        else:
            for step in self.enabled_steps():
                if should_stop_callback and should_stop_callback():
                    raise UnderstandingStoppedError("Evidence generation stopped by user")
                step_name = str(step["step"])
                component_id = str(step["component"])
                if not is_component_installed(component_id, self.model_dir):
                    logger.info(
                        "Skipping unavailable understanding component %s (%s)",
                        component_id,
                        step_name,
                    )
                    continue
                vision_key = TASK_TO_VISION_KEY.get(step_name, step_name)
                try:
                    component = self._get_component(component_id, step.get("params"))
                    bind_stop = getattr(component, "bind_should_stop_callback", None)
                    if callable(bind_stop):
                        bind_stop(should_stop_callback)
                    infer_result = component.infer(frame_bgr)
                    wrapped = self._wrap_step_result(
                        component_id,
                        step_name,
                        infer_result,
                    )
                    evidence["vision"][vision_key] = wrapped
                    if step_name == "image_caption":
                        tags = list(wrapped.get("tags") or [])
                except UnderstandingStoppedError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Understanding step failed (%s / %s): %s",
                        step_name,
                        component_id,
                        exc,
                    )

        return {
            "chunk_index": int(chunk_index),
            "start_sec": start_sec,
            "end_sec": end_sec,
            "sample": {
                "timestamp_sec": timestamp_sec,
                "strategy": self.keyframe_strategy,
            },
            "tags": tags,
            "evidence": evidence,
        }

    def _sample_timestamp(self, start_sec: float, end_sec: float) -> float:
        if self.keyframe_strategy == "midpoint":
            return float((start_sec + end_sec) / 2.0)
        return float((start_sec + end_sec) / 2.0)

    def _get_component(self, component_id: str, step_params: Mapping[str, Any] | None):
        cache_key = component_id
        if step_params:
            cache_key = f"{component_id}:{sorted(step_params.items())}"
        if cache_key not in self._component_cache:
            manifest_path = get_component_manifest_path(component_id, model_dir=self.model_dir)
            component_dir = os.path.dirname(manifest_path)
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            validated = validate_component_manifest(manifest, component_dir=component_dir)
            self._component_cache[cache_key] = build_understanding_component(
                validated,
                component_dir=component_dir,
                params=dict(step_params or {}),
            )
        return self._component_cache[cache_key]
