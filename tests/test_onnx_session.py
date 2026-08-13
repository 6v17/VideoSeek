import os
import unittest
from unittest.mock import patch

import onnxruntime as ort

from src.core.onnx_session import (
    build_session_options,
    gpu_backend_label,
    normalize_inference_ep,
    providers_indicate_gpu,
    resolve_embedding_batch_size,
    resolve_inference_ep,
    resolve_onnx_providers,
)


class OnnxSessionTests(unittest.TestCase):
    def test_resolve_embedding_batch_size_clamps_invalid_values(self):
        self.assertEqual(resolve_embedding_batch_size({"embedding_batch_size": "8"}), 8)
        self.assertEqual(resolve_embedding_batch_size({"embedding_batch_size": 0}), 1)
        self.assertEqual(resolve_embedding_batch_size({"embedding_batch_size": "bad"}), 16)

    def test_build_session_options_for_directml(self):
        options = build_session_options(prefer_gpu=True)

        self.assertFalse(options.enable_mem_pattern)
        self.assertEqual(options.execution_mode, ort.ExecutionMode.ORT_SEQUENTIAL)
        self.assertEqual(options.graph_optimization_level, ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED)
        self.assertEqual(options.inter_op_num_threads, 1)
        self.assertGreaterEqual(options.intra_op_num_threads, 1)
        self.assertLessEqual(options.intra_op_num_threads, 4)

    @patch.dict(os.environ, {"VIDEOSEEK_ORT_INTRA_OP_THREADS": "1"}, clear=False)
    def test_build_session_options_intra_threads_env_override(self):
        options = build_session_options(prefer_gpu=True)
        self.assertEqual(options.intra_op_num_threads, 1)

    def test_normalize_inference_ep_aliases(self):
        self.assertEqual(normalize_inference_ep("DirectML"), "dml")
        self.assertEqual(normalize_inference_ep("dx"), "dml")
        self.assertEqual(normalize_inference_ep("CUDA"), "cuda")
        self.assertEqual(normalize_inference_ep("weird"), "auto")

    @patch.dict(os.environ, {"VIDEOSEEK_INFERENCE_EP": "cuda"}, clear=False)
    def test_resolve_inference_ep_env_overrides_config(self):
        self.assertEqual(resolve_inference_ep({"inference_ep": "dml"}), "cuda")

    @patch.dict(os.environ, {"VIDEOSEEK_INFERENCE_EP": ""}, clear=False)
    def test_resolve_inference_ep_from_config(self):
        self.assertEqual(resolve_inference_ep({"inference_ep": "dml"}), "dml")

    @patch("src.core.onnx_session.get_available_onnx_provider_names")
    @patch.dict(os.environ, {"VIDEOSEEK_INFERENCE_EP": ""}, clear=False)
    def test_auto_prefers_cuda_when_available(self, mock_available):
        mock_available.return_value = [
            "CUDAExecutionProvider",
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        ]
        self.assertEqual(
            resolve_onnx_providers(prefer_gpu=True, config={"inference_ep": "auto"}),
            ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"],
        )

    @patch("src.core.onnx_session.get_available_onnx_provider_names")
    @patch.dict(os.environ, {"VIDEOSEEK_INFERENCE_EP": ""}, clear=False)
    def test_auto_filters_to_dml_on_stock_directml_wheel(self, mock_available):
        mock_available.return_value = ["DmlExecutionProvider", "CPUExecutionProvider"]
        self.assertEqual(
            resolve_onnx_providers(prefer_gpu=True, config={"inference_ep": "auto"}),
            ["DmlExecutionProvider", "CPUExecutionProvider"],
        )

    @patch("src.core.onnx_session.get_available_onnx_provider_names")
    @patch.dict(os.environ, {"VIDEOSEEK_INFERENCE_EP": ""}, clear=False)
    def test_cuda_forced_falls_back_to_dml_without_cuda_ep(self, mock_available):
        mock_available.return_value = ["DmlExecutionProvider", "CPUExecutionProvider"]
        self.assertEqual(
            resolve_onnx_providers(prefer_gpu=True, config={"inference_ep": "cuda"}),
            ["DmlExecutionProvider", "CPUExecutionProvider"],
        )

    @patch("src.core.onnx_session.get_available_onnx_provider_names")
    @patch.dict(os.environ, {"VIDEOSEEK_INFERENCE_EP": ""}, clear=False)
    def test_prefer_gpu_false_or_ep_cpu_forces_cpu(self, mock_available):
        mock_available.return_value = [
            "CUDAExecutionProvider",
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        ]
        self.assertEqual(resolve_onnx_providers(prefer_gpu=False, config={"inference_ep": "auto"}), ["CPUExecutionProvider"])
        self.assertEqual(resolve_onnx_providers(prefer_gpu=True, config={"inference_ep": "cpu"}), ["CPUExecutionProvider"])

    def test_providers_indicate_gpu_and_backend_label(self):
        self.assertTrue(providers_indicate_gpu([["CUDAExecutionProvider", "CPUExecutionProvider"]]))
        self.assertFalse(
            providers_indicate_gpu(
                [
                    ["CUDAExecutionProvider", "CPUExecutionProvider"],
                    ["CPUExecutionProvider"],
                ]
            )
        )
        self.assertEqual(
            gpu_backend_label([["CUDAExecutionProvider", "CPUExecutionProvider"]]),
            "CUDA",
        )
        self.assertEqual(
            gpu_backend_label([["DmlExecutionProvider", "CPUExecutionProvider"]]),
            "DirectML",
        )
        self.assertEqual(gpu_backend_label([["CPUExecutionProvider"]]), "CPU")


if __name__ == "__main__":
    unittest.main()
