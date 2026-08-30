from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

from src.app.logging_utils import get_logger
from src.core.understanding.base import UnderstandingStoppedError
from src.core.understanding.registry import build_understanding_component
from src.media.thumbnail import compose_side_by_side_bgr, get_single_thumbnail
from src.services.understanding_paths import get_component_manifest_path
from src.services.understanding_resource_service import is_component_installed, validate_component_manifest

logger = get_logger("understanding.pipeline")

TASK_TO_VISION_KEY = {
    "image_caption": "image_caption",
}

KEYFRAME_STRATEGY_MIDPOINT = "midpoint"
KEYFRAME_STRATEGY_INTERIOR_PAIR = "interior_pair"
KEYFRAME_STRATEGY_START_END = "start_end"  # accepted alias; samples are still interior
MIN_TWO_FRAME_SPAN_SEC = 0.8
# Near shot edges so motion is visible; keep a small inset so we do not sit on the cut.
INTERIOR_PAIR_LO = 0.12
INTERIOR_PAIR_HI = 0.88
MIN_INTERIOR_GAP_SEC = 0.25
TWO_FRAME_STRATEGIES = frozenset({KEYFRAME_STRATEGY_INTERIOR_PAIR, "start_end", "interior"})


def format_motion_vlm_context(
    *,
    chunk_start_sec: float,
    chunk_end_sec: float,
    timestamps_sec: list[float],
    language: str = "zh",
) -> str:
    """Per-chunk timing notes appended to the motion prompt (left=earlier, right=later)."""
    from src.services.understanding_resource_service import (
        CAPTION_LANGUAGE_ZH,
        normalize_caption_language,
    )

    stamps = [float(item) for item in timestamps_sec if item is not None]
    start = float(chunk_start_sec)
    end = float(chunk_end_sec)
    span = max(0.0, end - start)
    lang = normalize_caption_language(language)
    if len(stamps) >= 2:
        earlier, later = stamps[0], stamps[1]
        gap = max(0.0, later - earlier)
        if lang == CAPTION_LANGUAGE_ZH:
            return (
                f"左图较早（{earlier:.1f}s），右图较晚（{later:.1f}s），两帧间隔 {gap:.1f} 秒。"
                f"该语义段范围 {start:.1f}–{end:.1f} 秒（时长 {span:.1f} 秒）。"
                "按从早到晚描述画面变化；不要把左右当成同时发生的分屏。"
            )
        return (
            f"Left is earlier ({earlier:.1f}s), right is later ({later:.1f}s), "
            f"{gap:.1f}s apart. Chunk spans {start:.1f}–{end:.1f}s ({span:.1f}s). "
            "Describe change from earlier to later; this is not a simultaneous split screen."
        )
    stamp = stamps[0] if stamps else start + span / 2.0
    if lang == CAPTION_LANGUAGE_ZH:
        return (
            f"单帧取自段内 {stamp:.1f}s。该语义段范围 {start:.1f}–{end:.1f} 秒（时长 {span:.1f} 秒）。"
            "只写这一帧可见内容，不要编造未出现的动作。"
        )
    return (
        f"Single interior frame at {stamp:.1f}s. Chunk spans {start:.1f}–{end:.1f}s ({span:.1f}s). "
        "Describe only what is visible; do not invent motion that is not shown."
    )


def format_motion_frame_captions(
    timestamps_sec: list[float],
    *,
    language: str = "zh",
) -> tuple[str, str]:
    from src.services.understanding_resource_service import (
        CAPTION_LANGUAGE_ZH,
        normalize_caption_language,
    )

    stamps = [float(item) for item in timestamps_sec if item is not None]
    lang = normalize_caption_language(language)
    if len(stamps) < 2:
        stamp = stamps[0] if stamps else 0.0
        if lang == CAPTION_LANGUAGE_ZH:
            return (f"MID {stamp:.1f}s", "")
        return (f"MID {stamp:.1f}s", "")
    earlier, later = stamps[0], stamps[1]
    if lang == CAPTION_LANGUAGE_ZH:
        return (f"L earlier {earlier:.1f}s", f"R later {later:.1f}s")
    return (f"L earlier {earlier:.1f}s", f"R later {later:.1f}s")


def resolve_chunk_sample(start_sec: float, end_sec: float, *, strategy: str) -> dict[str, Any]:
    """Pick one or two sample times inside a chunk.

    Motion pairs sit near the shot ends (not 1/3–2/3) so a 1–2s cut still has
    visible change. Exact start/end are avoided. Sub-threshold spans stay one midpoint.
    """
    start = float(start_sec)
    end = float(end_sec)
    if end < start:
        end = start
    duration = end - start
    requested = str(strategy or KEYFRAME_STRATEGY_MIDPOINT).strip() or KEYFRAME_STRATEGY_MIDPOINT
    use_pair = requested in TWO_FRAME_STRATEGIES and duration >= MIN_TWO_FRAME_SPAN_SEC
    if use_pair:
        first = start + duration * INTERIOR_PAIR_LO
        last = start + duration * INTERIOR_PAIR_HI
        if last - first >= MIN_INTERIOR_GAP_SEC:
            return {
                "timestamp_sec": float(first),
                "timestamps_sec": [float(first), float(last)],
                "strategy": KEYFRAME_STRATEGY_INTERIOR_PAIR,
            }
    midpoint = start + (duration / 2.0) if duration else start
    return {
        "timestamp_sec": float(midpoint),
        "timestamps_sec": [float(midpoint)],
        "strategy": (
            KEYFRAME_STRATEGY_INTERIOR_PAIR
            if requested in TWO_FRAME_STRATEGIES
            else KEYFRAME_STRATEGY_MIDPOINT
        ),
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
        self.keyframe_strategy = str(defaults.get("keyframe_strategy", KEYFRAME_STRATEGY_MIDPOINT) or KEYFRAME_STRATEGY_MIDPOINT)
        self._component_cache: dict[str, Any] = {}
        from src.services.understanding_resource_service import (
            UNDERSTANDING_MODE_MOTION,
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
        if self.output_mode == UNDERSTANDING_MODE_MOTION:
            self.keyframe_strategy = KEYFRAME_STRATEGY_INTERIOR_PAIR

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
            tags = parse_vlm_tag_list(raw_text)
            if self.output_mode == UNDERSTANDING_MODE_TAGS:
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
                "tags": tags,
            }
        return {"source": component_id, **dict(infer_result)}

    def _decode_sample_frame(self, video_path: str, timestamp_sec: float):
        return get_single_thumbnail(video_path, timestamp_sec)

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
        sample = resolve_chunk_sample(start_sec, end_sec, strategy=self.keyframe_strategy)
        timestamps = list(sample.get("timestamps_sec") or [sample["timestamp_sec"]])
        from src.services.understanding_resource_service import (
            UNDERSTANDING_MODE_MOTION,
            get_remote_vlm_settings,
            normalize_caption_language,
        )

        language = normalize_caption_language(
            get_remote_vlm_settings(self.config).get("caption_language", "zh")
        )
        left_caption = right_caption = ""
        prompt_suffix = ""
        if self.output_mode == UNDERSTANDING_MODE_MOTION:
            left_caption, right_caption = format_motion_frame_captions(timestamps, language=language)
            prompt_suffix = format_motion_vlm_context(
                chunk_start_sec=start_sec,
                chunk_end_sec=end_sec,
                timestamps_sec=timestamps,
                language=language,
            )
        frames = [self._decode_sample_frame(video_path, stamp) for stamp in timestamps]
        if len(frames) >= 2:
            frame_bgr = compose_side_by_side_bgr(
                frames[0],
                frames[1],
                left_caption=left_caption,
                right_caption=right_caption,
            )
        elif frames:
            frame_bgr = frames[0]
            if left_caption:
                from src.media.thumbnail import draw_top_caption_bar

                frame_bgr = draw_top_caption_bar(frame_bgr, left_caption)
        else:
            frame_bgr = None
        evidence = {"vision": {}, "audio": {}}
        tags: list[str] = []

        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            logger.warning(
                "Keyframe decode failed for %s at %s (chunk %s)",
                video_path,
                timestamps,
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
                    try:
                        infer_result = component.infer(frame_bgr, prompt_suffix=prompt_suffix)
                    except TypeError:
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
            "sample": sample,
            "tags": tags,
            "evidence": evidence,
        }

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
