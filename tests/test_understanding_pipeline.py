import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from src.core.understanding.base import UnderstandingStoppedError
from src.core.understanding.pipeline import UnderstandingPipeline

PROFILE_MANIFEST = {
    "kind": "understanding_profile",
    "manifest_version": 1,
    "id": "vision_baseline_v1",
    "display_name": "视觉基础版",
    "install_relpath": "profiles/vision_baseline_v1",
    "requires": {
        "components": [
            "vision/image_caption/qwen3-vl-remote",
        ],
        "optional_components": [],
    },
    "pipeline": [
        {
            "step": "object_detection",
            "component": "vision/object_detection/legacy-detector",
            "enabled": True,
        },
        {
            "step": "image_caption",
            "component": "vision/image_caption/qwen3-vl-remote",
            "enabled": True,
        },
    ],
    "defaults": {"keyframe_strategy": "midpoint"},
}


class UnderstandingPipelineStopTests(unittest.TestCase):
    def test_enabled_steps_skips_object_detection(self):
        pipeline = UnderstandingPipeline(PROFILE_MANIFEST)
        steps = [str(item.get("step") or "") for item in pipeline.enabled_steps()]
        self.assertNotIn("object_detection", steps)
        self.assertIn("image_caption", steps)

    def test_run_video_chunks_honors_stop_between_chunks(self):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        pipeline = UnderstandingPipeline(PROFILE_MANIFEST)
        chunks = [{"start": 0.0, "end": 4.0}, {"start": 4.0, "end": 8.0}]
        calls = {"count": 0}

        def should_stop():
            calls["count"] += 1
            return calls["count"] > 1

        with (
            patch("src.core.understanding.pipeline.get_single_thumbnail", return_value=frame),
            patch.object(pipeline, "_get_component", return_value=MagicMock(infer=MagicMock(return_value={"text": "x"}))),
        ):
            with self.assertRaises(UnderstandingStoppedError):
                pipeline.run_video_chunks(
                    video_path="D:/Videos/demo.mp4",
                    chunks=chunks,
                    should_stop_callback=should_stop,
                )

    def test_run_chunk_skips_uninstalled_optional_components(self):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        pipeline = UnderstandingPipeline(PROFILE_MANIFEST)
        chunks = [{"start": 0.0, "end": 4.0}]

        def _installed(component_id, _model_dir=None):
            return component_id == "vision/image_caption/qwen3-vl-remote"

        caption_component = MagicMock(infer=MagicMock(return_value={"text": "a desk scene"}))

        with (
            patch("src.core.understanding.pipeline.get_single_thumbnail", return_value=frame),
            patch("src.core.understanding.pipeline.is_component_installed", side_effect=_installed),
            patch.object(pipeline, "_get_component", return_value=caption_component) as get_component,
        ):
            results = pipeline.run_video_chunks(
                video_path="D:/Videos/demo.mp4",
                chunks=chunks,
            )

        self.assertEqual(len(results), 1)
        self.assertNotIn("object_detection", results[0]["evidence"]["vision"])
        self.assertEqual(results[0]["evidence"]["vision"]["image_caption"]["text"], "a desk scene")
        get_component.assert_called_once()
