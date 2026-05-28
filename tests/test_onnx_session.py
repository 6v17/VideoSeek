import os
import unittest
from unittest.mock import patch

import onnxruntime as ort

from src.core.onnx_session import build_session_options, resolve_embedding_batch_size


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


if __name__ == "__main__":
    unittest.main()
