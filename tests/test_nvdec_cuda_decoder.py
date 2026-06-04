import unittest
from unittest.mock import MagicMock, patch

from src.core.nvdec_cuda_decoder import stream_frames_nvdec_cuda


class NvdecCudaDecoderTests(unittest.TestCase):
    @patch("src.core.nvdec_cuda_decoder._mark_decode_backend")
    @patch("src.core.gpu_clip_preprocess.retain_nvdec_gpu_frame", side_effect=lambda frame: frame)
    @patch("src.core.gpu_clip_preprocess._ensure_cupy_cuda_context")
    @patch("src.core.nvdec_cuda_decoder.get_video_duration_seconds", return_value=3.0)
    @patch("src.core.nvdec_cuda_decoder.get_video_stream_info", return_value={"width": 1920, "height": 1080, "pix_fmt": "yuv420p"})
    @patch("src.core.nvdec_cuda_decoder._create_decoder")
    def test_stream_samples_at_target_fps(self, mock_create, _ensure_ctx, _retain, _info, _duration, _mark):
        decoder = MagicMock()
        decoder.get_stream_metadata.return_value = MagicMock(duration=3.0)
        decoder.get_index_from_time_in_seconds.side_effect = lambda t: int(round(float(t) * 24))
        frame_a = object()
        frame_b = object()
        frame_c = object()
        decoder.get_batch_frames_by_index.return_value = [frame_a, frame_b, frame_c]
        mock_create.return_value = decoder

        pairs = list(stream_frames_nvdec_cuda("D:/video.mp4", 1.0))

        self.assertEqual(len(pairs), 3)
        self.assertEqual(pairs[0][1], 0.0)
        self.assertEqual(pairs[1][1], 1.0)
        self.assertEqual(pairs[2][1], 2.0)
        decoder.stop.assert_called_once()
        _mark.assert_called_once_with("nvdec_cuda_native")


if __name__ == "__main__":
    unittest.main()
