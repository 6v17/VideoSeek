"""Thumbnail helper tests."""

from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

from src.media.thumbnail import (
    get_single_thumbnail,
    is_blank_preview_frame,
    nudge_off_blank_frame,
    preview_max_drift_sec,
    preview_sample_time,
)


class ThumbnailHttpTests(unittest.TestCase):
    def test_http_url_skips_local_isfile_and_uses_ffmpeg(self):
        fake_frame = mock.Mock()
        fake_frame.size = 1
        with mock.patch("src.media.thumbnail._ffmpeg_capture_frame", return_value=fake_frame) as mock_ff:
            frame = get_single_thumbnail("http://192.168.1.2:18080/videos/lib1/a.mp4", 12.5)
        self.assertIs(frame, fake_frame)
        mock_ff.assert_called_once()

    def test_http_segment_blank_middle_tries_quarter_offsets(self):
        black = np.zeros((32, 32, 3), dtype=np.uint8)
        content = np.zeros((32, 32, 3), dtype=np.uint8)
        content[:, 8:24, :] = 160
        with mock.patch(
            "src.media.thumbnail._ffmpeg_capture_frame",
            side_effect=[black, content],
        ) as mock_ff:
            frame = get_single_thumbnail(
                "http://192.168.1.2:18080/videos/lib1/a.mp4",
                4.0,
                segment_start=0.0,
                segment_end=8.0,
            )
        self.assertIs(frame, content)
        self.assertEqual([item.args[1] for item in mock_ff.call_args_list], [4.0, 6.0])

    def test_missing_local_file_returns_none(self):
        frame = get_single_thumbnail("D:/missing/nope.mp4", 1.0)
        self.assertIsNone(frame)

    def test_span_sample_time_is_the_middle(self):
        self.assertEqual(preview_sample_time(10.0, 18.0), 14.0)
        self.assertEqual(preview_sample_time(10.0, 10.0), 10.0)
        self.assertIsNone(preview_max_drift_sec(10.0, 10.0))
        self.assertGreater(preview_max_drift_sec(0.0, 20.0), 1.5)

    def _local_capture(self, *, pos_ms: float, frame):
        capture = mock.Mock()
        capture.isOpened.return_value = True
        capture.read.return_value = (True, frame)
        capture.get.return_value = pos_ms
        cv2 = mock.Mock()
        cv2.CAP_PROP_POS_MSEC = 0
        cv2.VideoCapture.return_value = capture
        return cv2

    def test_near_keyframe_skips_ffmpeg(self):
        fast = mock.Mock()
        fast.size = 1
        cv2 = self._local_capture(pos_ms=13500, frame=fast)
        with (
            mock.patch("src.media.thumbnail.os.path.isfile", return_value=True),
            mock.patch("src.media.thumbnail._cv2", return_value=cv2),
            mock.patch("src.media.thumbnail._ffmpeg_capture_frame") as mock_ff,
        ):
            frame = get_single_thumbnail(r"D:\videos\a.mp4", 14.0, max_drift_sec=2.0)
        self.assertIs(frame, fast)
        mock_ff.assert_not_called()

    def test_far_keyframe_uses_ffmpeg(self):
        fast = mock.Mock()
        fast.size = 1
        accurate = mock.Mock()
        accurate.size = 1
        cv2 = self._local_capture(pos_ms=200, frame=fast)
        with (
            mock.patch("src.media.thumbnail.os.path.isfile", return_value=True),
            mock.patch("src.media.thumbnail._cv2", return_value=cv2),
            mock.patch("src.media.thumbnail._ffmpeg_capture_frame", return_value=accurate) as mock_ff,
        ):
            frame = get_single_thumbnail(r"D:\videos\a.mp4", 14.0, max_drift_sec=2.0)
        self.assertIs(frame, accurate)
        mock_ff.assert_called_once()

    def test_blank_flash_is_detected_without_treating_a_picture_as_blank(self):
        black = np.zeros((48, 64, 3), dtype=np.uint8)
        white = np.full((48, 64, 3), 255, dtype=np.uint8)
        picture = np.zeros((48, 64, 3), dtype=np.uint8)
        picture[:, 20:40, :] = 180
        self.assertTrue(is_blank_preview_frame(black))
        self.assertTrue(is_blank_preview_frame(white))
        self.assertFalse(is_blank_preview_frame(picture))

    def _content_frame(self):
        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        frame[:, 8:24, :] = 160
        return frame

    def test_quarter_after_middle_replaces_a_blank_middle(self):
        black = np.zeros((32, 32, 3), dtype=np.uint8)
        content = self._content_frame()
        capture = mock.Mock()
        cv2 = mock.Mock()
        with mock.patch(
            "src.media.thumbnail.read_captured_frame",
            return_value=(content, 6.0),
        ) as seek:
            picked = nudge_off_blank_frame(
                capture,
                cv2,
                black,
                4.0,
                start_sec=0.0,
                end_sec=8.0,
            )
        self.assertIs(picked, content)
        seek.assert_called_once()
        self.assertAlmostEqual(seek.call_args.args[2], 6.0)

    def test_quarter_before_middle_is_used_when_the_later_point_is_blank(self):
        black = np.zeros((32, 32, 3), dtype=np.uint8)
        content = self._content_frame()
        capture = mock.Mock()
        cv2 = mock.Mock()
        with mock.patch(
            "src.media.thumbnail.read_captured_frame",
            side_effect=[(black, 6.0), (content, 2.0)],
        ) as seek:
            picked = nudge_off_blank_frame(
                capture,
                cv2,
                black,
                4.0,
                start_sec=0.0,
                end_sec=8.0,
            )
        self.assertIs(picked, content)
        self.assertEqual([call.args[2] for call in seek.call_args_list], [6.0, 2.0])

    def test_blank_offsets_keep_the_middle_frame(self):
        black = np.zeros((32, 32, 3), dtype=np.uint8)
        capture = mock.Mock()
        cv2 = mock.Mock()
        with mock.patch(
            "src.media.thumbnail.read_captured_frame",
            side_effect=[(black, 6.0), (black, 2.0)],
        ):
            picked = nudge_off_blank_frame(
                capture,
                cv2,
                black,
                4.0,
                start_sec=0.0,
                end_sec=8.0,
            )
        self.assertIs(picked, black)

    def test_keyframe_outside_the_segment_is_skipped(self):
        black = np.zeros((32, 32, 3), dtype=np.uint8)
        outside = self._content_frame()
        inside = self._content_frame()
        inside[:, :, 2] = 40
        capture = mock.Mock()
        cv2 = mock.Mock()
        with mock.patch(
            "src.media.thumbnail.read_captured_frame",
            side_effect=[(outside, 0.0), (inside, 2.0)],
        ):
            picked = nudge_off_blank_frame(
                capture,
                cv2,
                black,
                5.0,
                start_sec=1.0,
                end_sec=9.0,
            )
        self.assertIs(picked, inside)

    def test_point_hit_does_not_leave_its_timestamp(self):
        black = np.zeros((32, 32, 3), dtype=np.uint8)
        capture = mock.Mock()
        cv2 = mock.Mock()
        with mock.patch("src.media.thumbnail.read_captured_frame") as seek:
            picked = nudge_off_blank_frame(
                capture,
                cv2,
                black,
                12.0,
                start_sec=12.0,
                end_sec=12.0,
            )
        self.assertIs(picked, black)
        seek.assert_not_called()

    def test_blank_frame_hit_uses_accurate_seek(self):
        black = np.zeros((32, 32, 3), dtype=np.uint8)
        accurate = self._content_frame()
        cv2 = self._local_capture(pos_ms=12000, frame=black)
        with (
            mock.patch("src.media.thumbnail.os.path.isfile", return_value=True),
            mock.patch("src.media.thumbnail._cv2", return_value=cv2),
            mock.patch(
                "src.media.thumbnail._ffmpeg_capture_frame",
                return_value=accurate,
            ) as mock_ff,
        ):
            frame = get_single_thumbnail(r"D:\videos\a.mp4", 12.0)
        self.assertIs(frame, accurate)
        mock_ff.assert_called_once()

    def test_non_blank_frame_hit_skips_accurate_seek(self):
        picture = self._content_frame()
        cv2 = self._local_capture(pos_ms=12000, frame=picture)
        with (
            mock.patch("src.media.thumbnail.os.path.isfile", return_value=True),
            mock.patch("src.media.thumbnail._cv2", return_value=cv2),
            mock.patch("src.media.thumbnail._ffmpeg_capture_frame") as mock_ff,
        ):
            frame = get_single_thumbnail(r"D:\videos\a.mp4", 12.0)
        self.assertIs(frame, picture)
        mock_ff.assert_not_called()


if __name__ == "__main__":
    unittest.main()
