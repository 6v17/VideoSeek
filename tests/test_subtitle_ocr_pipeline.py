import os
import unittest
from unittest import mock

import numpy as np

from src.core.subtitle_ocr import ocr_pipeline


class SubtitleOcrPipelineTests(unittest.TestCase):
    def test_overlap_collects_observations(self):
        frames = [
            (1.0, np.zeros((40, 80, 3), dtype=np.uint8) + 10),
            (2.0, np.zeros((40, 80, 3), dtype=np.uint8) + 40),
            (3.0, np.zeros((40, 80, 3), dtype=np.uint8) + 80),
        ]

        def fake_iter(_path, _times):
            yield from frames

        texts = {"2.0": "你好", "3.0": "世界"}

        def fake_ocr(roi):
            # Distinguish by mean brightness roughly matching our fake frames.
            mean = float(np.mean(roi))
            if mean < 25:
                return ""
            if mean < 60:
                return "你好"
            return "世界"

        with mock.patch.object(ocr_pipeline, "iter_frames_at_times", side_effect=fake_iter), mock.patch.object(
            ocr_pipeline, "roi_likely_blank", return_value=False
        ), mock.patch.object(ocr_pipeline, "crop_subtitle_roi", side_effect=lambda frame, **_k: frame), mock.patch.dict(
            os.environ, {"VIDEOSEEK_DISABLE_SUBTITLE_OCR_OVERLAP": "0"}, clear=False
        ):
            rows = ocr_pipeline.collect_ocr_observations(
                "dummy.mp4",
                [1.0, 2.0, 3.0],
                ocr_fn=fake_ocr,
                duration=10.0,
                asr_source="test",
            )
        self.assertEqual([r["text"] for r in rows], ["你好", "世界"])

    def test_serial_fallback_when_overlap_disabled(self):
        frames = [(1.0, np.ones((20, 40, 3), dtype=np.uint8) * 90)]

        def fake_iter(_path, _times):
            yield from frames

        with mock.patch.object(ocr_pipeline, "iter_frames_at_times", side_effect=fake_iter), mock.patch.object(
            ocr_pipeline, "roi_likely_blank", return_value=False
        ), mock.patch.object(ocr_pipeline, "crop_subtitle_roi", side_effect=lambda frame, **_k: frame), mock.patch.dict(
            os.environ, {"VIDEOSEEK_DISABLE_SUBTITLE_OCR_OVERLAP": "1"}, clear=False
        ):
            rows = ocr_pipeline.collect_ocr_observations(
                "dummy.mp4",
                [1.0],
                ocr_fn=lambda _roi: "字幕",
                duration=5.0,
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "字幕")


if __name__ == "__main__":
    unittest.main()
