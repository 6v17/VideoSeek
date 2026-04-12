import re as std_re
import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.modules.setdefault("faiss", types.SimpleNamespace())
sys.modules.setdefault("ftfy", types.SimpleNamespace(fix_text=lambda text: text))
sys.modules.setdefault("numpy", types.SimpleNamespace())
sys.modules.setdefault("regex", std_re)


class _SessionOptions:
    def __init__(self):
        self.enable_mem_pattern = True
        self.execution_mode = "parallel"


class _ExecutionMode:
    ORT_SEQUENTIAL = "sequential"


onnxruntime_stub = types.SimpleNamespace(
    SessionOptions=_SessionOptions,
    ExecutionMode=_ExecutionMode,
    get_available_providers=lambda: ["CPUExecutionProvider"],
)
sys.modules.setdefault("onnxruntime", onnxruntime_stub)

from src.core import clip_embedding


class ClipEmbeddingRuntimeTests(unittest.TestCase):
    def test_build_session_options_for_directml(self):
        options = clip_embedding._build_session_options(prefer_gpu=True)

        self.assertFalse(options.enable_mem_pattern)
        self.assertEqual(options.execution_mode, clip_embedding.ort.ExecutionMode.ORT_SEQUENTIAL)

    def test_detect_gpu_runtime_issue_reports_missing_directml_provider(self):
        with (
            patch("src.core.clip_embedding._is_windows", return_value=True),
            patch("src.core.clip_embedding._is_windows_10_1903_or_newer", return_value=True),
            patch("src.core.clip_embedding._is_directml_provider_available", return_value=False),
        ):
            issue = clip_embedding.detect_gpu_runtime_issue()

        self.assertEqual(issue, "directml")

    def test_detect_gpu_runtime_issue_reports_missing_directx_runtime(self):
        with (
            patch("src.core.clip_embedding._is_windows", return_value=True),
            patch("src.core.clip_embedding._is_windows_10_1903_or_newer", return_value=True),
            patch("src.core.clip_embedding._is_directml_provider_available", return_value=True),
            patch("src.core.clip_embedding._can_load_windows_dll", return_value=False),
        ):
            issue = clip_embedding.detect_gpu_runtime_issue()

        self.assertEqual(issue, "directx")


if __name__ == "__main__":
    unittest.main()
