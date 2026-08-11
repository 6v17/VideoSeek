import os
import unittest
from unittest import mock

import numpy as np

from src.core.subtitle_ocr import ocr_pipeline
from src.core.subtitle_ocr.rapidocr_engine import (
    _assign_texts_to_bands,
    ocr_frames_to_lines,
    resolve_rapidocr_config_path,
    resolve_subtitle_ocr_batch_size,
    stack_rois_vertically,
)


class SubtitleOcrBatchTests(unittest.TestCase):
    def test_resolve_batch_size_clamps(self):
        self.assertEqual(resolve_subtitle_ocr_batch_size(config={"subtitle_ocr_batch_size": 1}), 1)
        self.assertEqual(resolve_subtitle_ocr_batch_size(config={"subtitle_ocr_batch_size": 6}), 6)
        self.assertEqual(resolve_subtitle_ocr_batch_size(config={"subtitle_ocr_batch_size": 0}), 1)
        self.assertEqual(resolve_subtitle_ocr_batch_size(config={"subtitle_ocr_batch_size": 99}), 6)
        self.assertEqual(resolve_subtitle_ocr_batch_size(config={"subtitle_ocr_batch_size": "bad"}), 1)

    def test_resolve_rapidocr_config_path_materializes_when_missing(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing" / "config.yaml"
            with mock.patch(
                "src.core.subtitle_ocr.rapidocr_engine._iter_rapidocr_config_candidates",
                return_value=[missing],
            ), mock.patch(
                "src.infra.paths.get_app_data_dir",
                return_value=tmp,
            ):
                resolved = resolve_rapidocr_config_path()
            self.assertTrue(os.path.isfile(resolved))
            self.assertIn("Global:", Path(resolved).read_text(encoding="utf-8"))

    def test_stack_rois_bands_cover_each_roi(self):
        rois = [
            np.zeros((20, 40, 3), dtype=np.uint8) + 10,
            np.zeros((30, 50, 3), dtype=np.uint8) + 40,
            np.zeros((10, 20, 3), dtype=np.uint8) + 80,
        ]
        stacked, bands = stack_rois_vertically(rois, gap=8)
        self.assertEqual(len(bands), 3)
        self.assertEqual(stacked.shape[1], 50)
        heights = [b[1] - b[0] for b in bands]
        self.assertEqual(heights, [20, 30, 10])
        # Gaps sit between bands, not inside them.
        self.assertEqual(bands[1][0], bands[0][1] + 8)
        self.assertEqual(bands[2][0], bands[1][1] + 8)

    def test_assign_texts_to_bands_orders_within_band(self):
        bands = [(0, 20), (28, 58)]
        rows = [
            {"text": "B", "score": 0.9, "y_center": 40.0, "x_center": 30.0},
            {"text": "A", "score": 0.9, "y_center": 40.0, "x_center": 5.0},
            {"text": "top", "score": 0.8, "y_center": 10.0, "x_center": 1.0},
        ]
        lines, ambiguous = _assign_texts_to_bands(rows, bands, min_score=0.45, join_with=" ")
        self.assertFalse(ambiguous)
        self.assertEqual(lines, ["top", "A B"])

    def test_assign_texts_ambiguous_when_on_gap(self):
        bands = [(0, 20), (28, 58)]
        rows = [{"text": "x", "score": 0.9, "y_center": 24.0, "x_center": 1.0}]
        lines, ambiguous = _assign_texts_to_bands(rows, bands, min_score=0.45, join_with=" ")
        self.assertTrue(ambiguous)
        self.assertIsNone(lines)

    def test_ocr_image_bgr_falls_back_to_cpu_on_ort_fail(self):
        from src.core.subtitle_ocr import rapidocr_engine as engine

        frame = np.zeros((20, 40, 3), dtype=np.uint8) + 10
        gpu_engine = mock.Mock(side_effect=RuntimeError("onnxruntime.capi.onnxruntime_pybind11_state.Fail: DML"))
        cpu_engine = mock.Mock(return_value=([["hello", 0.9]], None))

        engine.reset_rapidocr_runtime_state()
        try:
            with mock.patch.object(
                engine,
                "get_rapidocr_engine",
                side_effect=[gpu_engine, cpu_engine],
            ) as get_engine:
                rows = engine.ocr_image_bgr(frame, prefer_gpu=True)
            self.assertEqual(rows[0]["text"], "hello")
            self.assertEqual(get_engine.call_count, 2)
            self.assertFalse(get_engine.call_args_list[1].kwargs.get("prefer_gpu"))
            self.assertFalse(engine._effective_prefer_gpu(True))
        finally:
            engine.reset_rapidocr_runtime_state()

    def test_is_ort_runtime_fail_detects_wrapped_error(self):
        from src.core.subtitle_ocr.rapidocr_engine import _is_ort_runtime_fail

        class ONNXRuntimeError(Exception):
            pass

        wrapped = ONNXRuntimeError(
            "Traceback...\nonnxruntime.capi.onnxruntime_pybind11_state.Fail: [ONNXRuntimeError] : 1"
        )
        self.assertTrue(_is_ort_runtime_fail(wrapped))
        self.assertFalse(_is_ort_runtime_fail(ValueError("bad image")))

    def test_ocr_frames_stacked_gpu_fail_falls_back_per_frame(self):
        from src.core.subtitle_ocr import rapidocr_engine as engine

        frames = [
            np.zeros((20, 40, 3), dtype=np.uint8) + 10,
            np.zeros((20, 40, 3), dtype=np.uint8) + 40,
        ]
        engine.reset_rapidocr_runtime_state()
        try:
            with mock.patch.object(
                engine,
                "ocr_image_bgr",
                side_effect=RuntimeError("onnxruntime.capi.onnxruntime_pybind11_state.Fail"),
            ) as stacked, mock.patch.object(
                engine,
                "ocr_frame_to_line",
                side_effect=["甲", "乙"],
            ) as per_frame:
                lines = ocr_frames_to_lines(frames, prefer_gpu=True)
            self.assertEqual(lines, ["甲", "乙"])
            self.assertEqual(per_frame.call_count, 2)
            # Stacked call must not silently retry the tall image on CPU.
            self.assertEqual(stacked.call_count, 1)
            self.assertFalse(stacked.call_args.kwargs.get("allow_cpu_retry", True))
        finally:
            engine.reset_rapidocr_runtime_state()

    def test_ocr_frames_skips_stack_when_force_cpu(self):
        from src.core.subtitle_ocr import rapidocr_engine as engine

        frames = [
            np.zeros((20, 40, 3), dtype=np.uint8) + 10,
            np.zeros((20, 40, 3), dtype=np.uint8) + 40,
        ]
        engine.reset_rapidocr_runtime_state()
        try:
            engine._FORCE_CPU = True
            with mock.patch.object(
                engine,
                "ocr_image_bgr",
            ) as stacked, mock.patch.object(
                engine,
                "ocr_frame_to_line",
                side_effect=["一", "二"],
            ):
                lines = ocr_frames_to_lines(frames, prefer_gpu=True)
            self.assertEqual(lines, ["一", "二"])
            stacked.assert_not_called()
        finally:
            engine.reset_rapidocr_runtime_state()

    def test_pipeline_batches_rois(self):
        frames = [
            (1.0, np.zeros((20, 40, 3), dtype=np.uint8) + 10),
            (2.0, np.zeros((20, 40, 3), dtype=np.uint8) + 40),
            (3.0, np.zeros((20, 40, 3), dtype=np.uint8) + 80),
        ]
        batch_calls = []

        def fake_iter(_path, _times):
            yield from frames

        def fake_batch(rois):
            batch_calls.append(len(rois))
            return [f"t{i}" for i in range(len(rois))]

        with mock.patch.object(ocr_pipeline, "iter_frames_at_times", side_effect=fake_iter), mock.patch.object(
            ocr_pipeline, "roi_likely_blank", return_value=False
        ), mock.patch.object(
            ocr_pipeline, "crop_subtitle_rois", side_effect=lambda frame, **_k: [("bottom", frame)]
        ), mock.patch.dict(
            __import__("os").environ, {"VIDEOSEEK_DISABLE_SUBTITLE_OCR_OVERLAP": "1"}, clear=False
        ):
            rows = ocr_pipeline.collect_ocr_observations(
                "dummy.mp4",
                [1.0, 2.0, 3.0],
                ocr_fn=lambda _roi: "unused",
                ocr_batch_fn=fake_batch,
                batch_size=2,
                duration=10.0,
            )
        self.assertEqual(batch_calls, [2, 1])
        self.assertEqual([r["text"] for r in rows], ["t0", "t1", "t0"])


if __name__ == "__main__":
    unittest.main()
