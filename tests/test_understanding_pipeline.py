import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from src.core.understanding.base import UnderstandingStoppedError
from src.core.understanding.pipeline import (
    UnderstandingPipeline,
    format_motion_vlm_context,
    resolve_chunk_sample,
)

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


class UnderstandingKeyframeSampleTests(unittest.TestCase):
    def test_midpoint_sample(self):
        sample = resolve_chunk_sample(0.0, 10.0, strategy="midpoint")
        self.assertEqual(sample["strategy"], "midpoint")
        self.assertEqual(sample["timestamps_sec"], [5.0])
        self.assertAlmostEqual(sample["timestamp_sec"], 5.0)

    def test_interior_pair_avoids_chunk_edges(self):
        sample = resolve_chunk_sample(10.0, 20.0, strategy="interior_pair")
        self.assertEqual(sample["strategy"], "interior_pair")
        self.assertEqual(len(sample["timestamps_sec"]), 2)
        first, last = sample["timestamps_sec"]
        self.assertAlmostEqual(first, 11.2)
        self.assertAlmostEqual(last, 18.8)
        self.assertGreater(first, 10.0)
        self.assertLess(last, 20.0)

    def test_interior_pair_spreads_short_shot(self):
        sample = resolve_chunk_sample(0.0, 1.5, strategy="interior_pair")
        first, last = sample["timestamps_sec"]
        self.assertAlmostEqual(first, 0.18)
        self.assertAlmostEqual(last, 1.32)
        self.assertGreater(last - first, 1.0)

    def test_interior_pair_short_chunk_single_frame(self):
        sample = resolve_chunk_sample(1.0, 1.2, strategy="interior_pair")
        self.assertEqual(len(sample["timestamps_sec"]), 1)
        self.assertAlmostEqual(sample["timestamp_sec"], 1.1)

    def test_motion_mode_stitches_start_and_end_frames(self):
        left = np.zeros((40, 60, 3), dtype=np.uint8)
        right = np.full((40, 60, 3), 255, dtype=np.uint8)
        pipeline = UnderstandingPipeline(PROFILE_MANIFEST, output_mode="motion")
        chunks = [{"start": 0.0, "end": 8.0}]
        caption_component = MagicMock(infer=MagicMock(return_value={"text": "the figure raises a hand"}))

        with (
            patch("src.core.understanding.pipeline.get_single_thumbnail", side_effect=[left, right]),
            patch("src.core.understanding.pipeline.is_component_installed", return_value=True),
            patch.object(pipeline, "_get_component", return_value=caption_component),
        ):
            results = pipeline.run_video_chunks(video_path="D:/Videos/demo.mp4", chunks=chunks)

        self.assertEqual(results[0]["sample"]["strategy"], "interior_pair")
        self.assertEqual(len(results[0]["sample"]["timestamps_sec"]), 2)
        first, last = results[0]["sample"]["timestamps_sec"]
        self.assertGreater(first, 0.0)
        self.assertLess(last, 8.0)
        stitched = caption_component.infer.call_args[0][0]
        self.assertEqual(stitched.shape[1], 120)
        self.assertGreater(stitched.shape[0], 40)
        suffix = caption_component.infer.call_args.kwargs.get("prompt_suffix") or ""
        self.assertIn("间隔", suffix)
        self.assertIn("左图较早", suffix)
        self.assertEqual(results[0]["evidence"]["vision"]["image_caption"]["text"], "the figure raises a hand")
        self.assertEqual(pipeline.keyframe_strategy, "interior_pair")

    def test_motion_context_includes_order_and_gap(self):
        text = format_motion_vlm_context(
            chunk_start_sec=10.0,
            chunk_end_sec=20.0,
            timestamps_sec=[13.3, 16.7],
            language="zh",
        )
        self.assertIn("13.3s", text)
        self.assertIn("16.7s", text)
        self.assertIn("3.4", text)
        self.assertIn("10.0", text)
        en = format_motion_vlm_context(
            chunk_start_sec=10.0,
            chunk_end_sec=20.0,
            timestamps_sec=[13.3, 16.7],
            language="en",
        )
        self.assertIn("earlier", en)
        self.assertIn("3.4s apart", en)
