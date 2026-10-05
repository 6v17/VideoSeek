import unittest
from unittest.mock import patch

import numpy as np

from src.core.timestamp_health import assess_index_timestamp_health


class TimestampHealthTests(unittest.TestCase):
    @patch("src.core.timestamp_health.get_video_duration_seconds", return_value=100.0)
    @patch("src.core.timestamp_health.probe_stream_timing")
    @patch("src.core.timestamp_health.resolve_sampling_fps", return_value=1.0)
    def test_detects_duration_drift(self, _mock_fps, mock_probe, _mock_duration):
        mock_probe.return_value = {
            "duration": 100.0,
            "r_frame_rate": 30.0,
            "avg_frame_rate": 30.0,
        }
        timestamps = np.linspace(0.0, 50.0, 51)

        result = assess_index_timestamp_health("D:/long.mp4", timestamps, config={"fps": 1})

        self.assertIn("duration_drift", result["warnings"])
        self.assertIn("50.00s", result["detail"])

    @patch("src.core.timestamp_health.get_video_duration_seconds", return_value=60.0)
    @patch("src.core.timestamp_health.probe_stream_timing")
    @patch("src.core.timestamp_health.resolve_sampling_fps", return_value=1.0)
    def test_detects_vfr_suspected(self, _mock_fps, mock_probe, _mock_duration):
        mock_probe.return_value = {
            "duration": 60.0,
            "r_frame_rate": 60.0,
            "avg_frame_rate": 24.0,
        }
        timestamps = np.linspace(0.0, 59.0, 60)

        result = assess_index_timestamp_health("D:/vfr.mp4", timestamps, config={"fps": 1})

        self.assertIn("vfr_suspected", result["warnings"])

    @patch("src.core.timestamp_health.get_video_duration_seconds", return_value=10.0)
    @patch("src.core.timestamp_health.probe_stream_timing")
    @patch("src.core.timestamp_health.resolve_sampling_fps", return_value=1.0)
    def test_healthy_timestamps_return_no_warnings(self, _mock_fps, mock_probe, _mock_duration):
        mock_probe.return_value = {
            "duration": 10.0,
            "r_frame_rate": 30.0,
            "avg_frame_rate": 30.0,
        }
        timestamps = np.linspace(0.0, 9.0, 10)

        result = assess_index_timestamp_health("D:/ok.mp4", timestamps, config={"fps": 1})

        self.assertEqual(result["warnings"], [])


if __name__ == "__main__":
    unittest.main()
