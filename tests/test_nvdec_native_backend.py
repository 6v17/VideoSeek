import os
import unittest
from unittest.mock import MagicMock, patch

from src.core import extract_frames as ef


class NvdecNativeBackendTests(unittest.TestCase):
    @patch.dict(os.environ, {"VIDEOSEEK_INFERENCE_EP": "cuda", "VIDEOSEEK_CUDA_ZERO_COPY": "1"}, clear=False)
    @patch("src.core.extract_frames.cupy_available", return_value=True)
    @patch("src.core.extract_frames.pynvvideocodec_available", return_value=True)
    @patch("src.core.extract_frames.system_has_nvidia_gpu", return_value=True)
    @patch("src.core.extract_frames.load_config", return_value={"experimental_hw_decode": False})
    def test_cuda_zero_copy_enabled_when_deps_present(self, _cfg, _gpu, _pynv, _cupy):
        self.assertTrue(ef.cuda_zero_copy_indexing_enabled())

    @patch.dict(os.environ, {"VIDEOSEEK_CUDA_ZERO_COPY": "0"}, clear=False)
    @patch("src.core.extract_frames.cupy_available", return_value=True)
    @patch("src.core.extract_frames.pynvvideocodec_available", return_value=True)
    def test_cuda_zero_copy_disabled_by_env(self, _pynv, _cupy):
        self.assertFalse(ef.cuda_zero_copy_indexing_enabled())

    @patch.dict(os.environ, {"VIDEOSEEK_INFERENCE_EP": "cuda"}, clear=False)
    @patch("src.core.extract_frames.cupy_available", return_value=True)
    @patch("src.core.extract_frames.pynvvideocodec_available", return_value=True)
    @patch("src.core.extract_frames.system_has_nvidia_gpu", return_value=True)
    @patch("src.core.extract_frames.gpu_scale_decode_enabled", return_value=True)
    @patch("src.core.extract_frames.ffmpeg_supports_cuda_hwaccel", return_value=True)
    @patch("src.core.extract_frames.is_gpu_decode_experiment_active", return_value=True)
    @patch("src.core.extract_frames.get_video_stream_info", return_value={"pix_fmt": "yuv420p", "profile": "main"})
    def test_resolve_backends_prefers_nvdec_cuda_native(
        self,
        _info,
        _active,
        _cuda,
        _scale,
        _nvidia,
        _pynv,
        _cupy,
    ):
        backends = ef._resolve_decode_backends("D:/video.mp4")
        self.assertEqual(backends[0], "nvdec_cuda_native")
        self.assertIn("nvdec_cuda_scale", backends)


if __name__ == "__main__":
    unittest.main()
