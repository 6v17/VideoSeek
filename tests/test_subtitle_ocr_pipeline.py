import os
import unittest
from unittest import mock

import numpy as np

from src.core.subtitle_ocr import ocr_pipeline
from src.core.subtitle_ocr.frame_sample import (
    roi_changed,
    roi_fingerprint,
    roi_fingerprints_similar,
    roi_likely_blank,
)


class SubtitleOcrPipelineTests(unittest.TestCase):
    def test_overlap_collects_observations(self):
        frames = [
            (1.0, np.zeros((40, 80, 3), dtype=np.uint8) + 10),
            (2.0, np.zeros((40, 80, 3), dtype=np.uint8) + 40),
            (3.0, np.zeros((40, 80, 3), dtype=np.uint8) + 80),
        ]

        def fake_iter(_path, _times):
            yield from frames

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
        ), mock.patch.object(ocr_pipeline, "crop_subtitle_rois", side_effect=lambda frame, **_k: [("bottom", frame)]), mock.patch.dict(
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
        ), mock.patch.object(ocr_pipeline, "crop_subtitle_rois", side_effect=lambda frame, **_k: [("bottom", frame)]), mock.patch.dict(
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

    def test_blank_skips_without_ocr(self):
        frames = [
            (1.0, np.zeros((40, 80, 3), dtype=np.uint8)),
            (2.0, np.ones((40, 80, 3), dtype=np.uint8) * 90),
        ]
        ocr_calls = []

        def fake_iter(_path, _times):
            yield from frames

        def fake_ocr(roi):
            ocr_calls.append(float(np.mean(roi)))
            return "有字"

        with mock.patch.object(ocr_pipeline, "iter_frames_at_times", side_effect=fake_iter), mock.patch.object(
            ocr_pipeline,
            "roi_likely_blank",
            side_effect=lambda roi, **_k: float(np.mean(roi)) < 5.0,
        ), mock.patch.object(ocr_pipeline, "crop_subtitle_rois", side_effect=lambda frame, **_k: [("bottom", frame)]), mock.patch.dict(
            os.environ, {"VIDEOSEEK_DISABLE_SUBTITLE_OCR_OVERLAP": "1"}, clear=False
        ):
            stats: dict[str, int] = {}
            rows = ocr_pipeline.collect_ocr_observations(
                "dummy.mp4",
                [1.0, 2.0],
                ocr_fn=fake_ocr,
                duration=5.0,
                stats_out=stats,
            )
        self.assertEqual([r["text"] for r in rows], ["有字"])
        self.assertEqual(len(ocr_calls), 1)
        self.assertEqual(stats["blank_skips"], 1)
        self.assertEqual(stats["ocr_calls"], 1)
        self.assertEqual(stats["probed"], 2)

    def test_unchanged_roi_skips_ocr_and_extends_cue(self):
        plate = np.ones((40, 80, 3), dtype=np.uint8) * 120
        plate[10:20, 10:70] = 20  # fake ink
        frames = [
            (1.0, plate.copy()),
            (2.0, plate.copy()),
            (3.0, plate.copy()),
        ]
        ocr_calls = []

        def fake_iter(_path, _times):
            yield from frames

        def fake_ocr(_roi):
            ocr_calls.append(1)
            return "固定字幕"

        with mock.patch.object(ocr_pipeline, "iter_frames_at_times", side_effect=fake_iter), mock.patch.object(
            ocr_pipeline, "roi_likely_blank", return_value=False
        ), mock.patch.object(ocr_pipeline, "crop_subtitle_rois", side_effect=lambda frame, **_k: [("bottom", frame)]), mock.patch.dict(
            os.environ, {"VIDEOSEEK_DISABLE_SUBTITLE_OCR_OVERLAP": "1"}, clear=False
        ):
            stats: dict[str, int] = {}
            rows = ocr_pipeline.collect_ocr_observations(
                "dummy.mp4",
                [1.0, 2.0, 3.0],
                ocr_fn=fake_ocr,
                duration=10.0,
                stats_out=stats,
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "固定字幕")
        self.assertEqual(len(ocr_calls), 1)
        self.assertEqual(stats["ocr_calls"], 1)
        self.assertEqual(stats["unchanged_skips"], 2)
        self.assertGreaterEqual(float(rows[0]["end"]), 4.0)

    def test_top_and_bottom_bands_keep_separate_cues(self):
        top = np.ones((30, 80, 3), dtype=np.uint8) * 200
        bottom = np.ones((40, 80, 3), dtype=np.uint8) * 40
        bottom[10:20, 10:70] = 20
        frames = [(1.0, np.zeros((100, 80, 3), dtype=np.uint8))]

        def fake_iter(_path, _times):
            yield from frames

        def fake_ocr(roi):
            mean = float(np.mean(roi))
            return "顶部标题" if mean > 100 else "底部对白"

        with mock.patch.object(ocr_pipeline, "iter_frames_at_times", side_effect=fake_iter), mock.patch.object(
            ocr_pipeline, "roi_likely_blank", return_value=False
        ), mock.patch.object(
            ocr_pipeline,
            "crop_subtitle_rois",
            side_effect=lambda frame, **_k: [("top", top.copy()), ("bottom", bottom.copy())],
        ), mock.patch.dict(os.environ, {"VIDEOSEEK_DISABLE_SUBTITLE_OCR_OVERLAP": "1"}, clear=False):
            rows = ocr_pipeline.collect_ocr_observations(
                "dummy.mp4",
                [1.0],
                ocr_fn=fake_ocr,
                duration=5.0,
                include_top_band=True,
            )
        self.assertEqual([r["text"] for r in rows], ["顶部标题", "底部对白"])


class SubtitleRoiBlankTests(unittest.TestCase):
    def test_flat_gray_is_blank(self):
        flat = np.ones((80, 320, 3), dtype=np.uint8) * 40
        self.assertTrue(roi_likely_blank(flat))

    def test_thin_white_hardsub_is_not_blank(self):
        import cv2

        hard = np.zeros((120, 640, 3), dtype=np.uint8)
        cv2.putText(
            hard,
            "Sample Subtitle",
            (90, 95),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        self.assertFalse(roi_likely_blank(hard))


class SubtitleRoiFingerprintTests(unittest.TestCase):
    def test_fingerprint_stable_for_same_plate(self):
        plate = np.ones((48, 96, 3), dtype=np.uint8) * 90
        plate[12:24, 8:88] = 30
        left = roi_fingerprint(plate)
        right = roi_fingerprint(plate.copy())
        self.assertTrue(roi_fingerprints_similar(left, right))

    def test_roi_changed_detects_new_plate(self):
        a = np.ones((48, 96, 3), dtype=np.uint8) * 40
        b = np.ones((48, 96, 3), dtype=np.uint8) * 200
        changed, fp = roi_changed(a, None)
        self.assertTrue(changed)
        changed_same, fp2 = roi_changed(a.copy(), fp)
        self.assertFalse(changed_same)
        self.assertTrue(np.array_equal(fp, fp2))
        changed_new, _fp3 = roi_changed(b, fp)
        self.assertTrue(changed_new)

    def test_roi_changed_detects_glyph_layout_swap(self):
        a = np.ones((120, 640, 3), dtype=np.uint8) * 40
        b = a.copy()
        a[70:98, 80:400] = 220
        b[70:98, 200:520] = 220
        changed, fp = roi_changed(a, None)
        self.assertTrue(changed)
        changed_new, _ = roi_changed(b, fp)
        self.assertTrue(changed_new)


if __name__ == "__main__":
    unittest.main()
