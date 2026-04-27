import os
import re as std_re
import sys
import types
import unittest
from unittest.mock import patch

sys.modules.pop("numpy", None)
import numpy as np

sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.modules.setdefault("faiss", types.SimpleNamespace())
sys.modules.setdefault("ftfy", types.SimpleNamespace(fix_text=lambda text: text))
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
    def test_run_visual_batch_splits_failed_batch_until_single_frame(self):
        class FakeSession:
            def __init__(self):
                self.batch_sizes = []

            def run(self, _outputs, inputs):
                batch = inputs["input"]
                self.batch_sizes.append(int(batch.shape[0]))
                if batch.shape[0] > 1:
                    raise RuntimeError("temporary batch failure")
                return [np.array([[1.0, 0.0]], dtype=np.float32)]

        engine = clip_embedding.CLIPOnnxEngine.__new__(clip_embedding.CLIPOnnxEngine)
        engine.visual_session = FakeSession()
        engine.active_providers = {"visual": ["CPUExecutionProvider"], "text": ["CPUExecutionProvider"]}
        engine.using_gpu = False
        engine.backend_label = "CPU"
        engine.runtime_warning = ""
        engine._cpu_visual_session = None
        engine._visual_force_cpu = False
        engine._feature_dim = 2

        batch = [np.zeros((3, 224, 224), dtype=np.float32), np.zeros((3, 224, 224), dtype=np.float32)]
        result = engine._run_visual_batch(batch)

        self.assertEqual(result.shape, (2, 2))
        self.assertEqual(engine.visual_session.batch_sizes, [2, 1, 1])

    def test_run_visual_batch_falls_back_to_cpu_after_gpu_single_frame_failure(self):
        class FailingGpuSession:
            def __init__(self):
                self.calls = 0

            def run(self, _outputs, _inputs):
                self.calls += 1
                raise RuntimeError("DirectML GPU out of memory")

        class CpuSession:
            def __init__(self):
                self.calls = 0

            def run(self, _outputs, _inputs):
                self.calls += 1
                return [np.array([[0.0, 1.0]], dtype=np.float32)]

        engine = clip_embedding.CLIPOnnxEngine.__new__(clip_embedding.CLIPOnnxEngine)
        engine.visual_session = FailingGpuSession()
        engine.active_providers = {"visual": ["DmlExecutionProvider"], "text": ["DmlExecutionProvider"]}
        engine.using_gpu = True
        engine.backend_label = "GPU"
        engine.runtime_warning = ""
        engine._feature_dim = 2
        engine._cpu_visual_session = None
        engine._visual_force_cpu = False

        cpu_session = CpuSession()
        engine._create_cpu_visual_session = lambda: cpu_session

        batch = [np.zeros((3, 224, 224), dtype=np.float32)]
        first = engine._run_visual_batch(batch)
        second = engine._run_visual_batch(batch)

        self.assertEqual(first.shape, (1, 2))
        self.assertEqual(second.shape, (1, 2))
        self.assertEqual(engine.visual_session.calls, 1)
        self.assertEqual(cpu_session.calls, 2)
        self.assertTrue(engine._visual_force_cpu)
        self.assertFalse(engine.using_gpu)
        self.assertEqual(engine.backend_label, "CPU")
        self.assertIn("fell back to CPU", engine.runtime_warning)

    def test_resolve_embedding_batch_size_clamps_invalid_values(self):
        self.assertEqual(clip_embedding._resolve_embedding_batch_size({"embedding_batch_size": "8"}), 8)
        self.assertEqual(clip_embedding._resolve_embedding_batch_size({"embedding_batch_size": 0}), 1)
        self.assertEqual(clip_embedding._resolve_embedding_batch_size({"embedding_batch_size": "bad"}), 16)

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

    @patch("src.core.clip_embedding._run_gpu_runtime_probe_once", return_value={"ok": False, "issue": "directx", "detail": "probe crashed"})
    def test_prepare_inference_runtime_falls_back_to_cpu_when_probe_fails(self, _mock_probe):
        status = clip_embedding.prepare_inference_runtime(prefer_gpu=True)

        self.assertFalse(status["effective_prefer_gpu"])
        self.assertEqual(status["issue"], "directx")
        self.assertIn("probe crashed", status["warning"])

    @patch("src.core.clip_embedding._run_gpu_runtime_probe_once", return_value={"ok": True, "issue": "", "detail": ""})
    def test_prepare_inference_runtime_keeps_gpu_when_probe_succeeds(self, _mock_probe):
        status = clip_embedding.prepare_inference_runtime(prefer_gpu=True)

        self.assertTrue(status["effective_prefer_gpu"])
        self.assertEqual(status["warning"], "")

    def test_parse_gpu_probe_payload_uses_last_json_line(self):
        payload = clip_embedding._parse_gpu_probe_payload("noise\n{\"ok\": false, \"issue\": \"unknown\", \"detail\": \"x\"}\n")

        self.assertEqual(payload["issue"], "unknown")

    @patch("src.core.clip_embedding.os.path.exists", return_value=True)
    @patch("src.core.clip_embedding.sys.frozen", False, create=True)
    @patch("src.core.clip_embedding.sys.executable", "C:/Python/python.exe", create=True)
    def test_build_gpu_probe_command_uses_main_script_in_dev_mode(self, _mock_exists):
        command = clip_embedding._build_gpu_probe_command()

        self.assertEqual(os.path.normpath(command[0]), os.path.normpath("C:/Python/python.exe"))
        self.assertTrue(command[1].endswith("main.py"))
        self.assertEqual(command[2], "--gpu-probe")

    @patch("src.core.clip_embedding.os.path.exists", return_value=True)
    @patch("src.core.clip_embedding.sys.frozen", True, create=True)
    @patch("src.core.clip_embedding.sys.executable", "", create=True)
    @patch("src.core.clip_embedding.sys.argv", ["D:/VideoSeek/VideoSeek.exe"], create=True)
    def test_build_gpu_probe_command_uses_argv0_for_frozen_app_when_sys_executable_missing(self, _mock_exists):
        command = clip_embedding._build_gpu_probe_command()

        self.assertEqual(command, [os.path.abspath("D:/VideoSeek/VideoSeek.exe"), "--gpu-probe"])

    @patch("src.core.clip_embedding.os.path.exists", return_value=True)
    @patch("src.core.clip_embedding.sys.frozen", False, create=True)
    @patch("src.core.clip_embedding.sys.executable", "", create=True)
    @patch("src.core.clip_embedding.sys.argv", ["D:/VideoSeek/VideoSeek.exe"], create=True)
    def test_build_gpu_probe_command_uses_exe_even_when_frozen_flag_is_missing(self, _mock_exists):
        command = clip_embedding._build_gpu_probe_command()

        self.assertEqual(command, [os.path.abspath("D:/VideoSeek/VideoSeek.exe"), "--gpu-probe"])

    @patch("src.core.clip_embedding._run_isolated_gpu_probe", return_value={"ok": False, "issue": "directx", "detail": "broken"})
    @patch("builtins.print")
    def test_gpu_probe_cli_main_returns_failure_exit_code(self, mock_print, _mock_probe):
        exit_code = clip_embedding.gpu_probe_cli_main()

        self.assertEqual(exit_code, 1)
        mock_print.assert_called_once()

    @patch("src.core.clip_embedding.load_config", return_value={"prefer_gpu": True})
    def test_get_engine_runtime_status_uses_probe_cache_before_engine_init(self, _mock_load_config):
        clip_embedding._GPU_PROBE_CACHE = {"ok": True, "issue": "", "detail": ""}
        self.addCleanup(lambda: setattr(clip_embedding, "_GPU_PROBE_CACHE", None))
        self.addCleanup(lambda: setattr(clip_embedding, "engine", None))
        clip_embedding.engine = None

        status = clip_embedding.get_engine_runtime_status()

        self.assertTrue(status["initialized"])
        self.assertEqual(status["backend"], "GPU")

    @patch("src.core.clip_embedding.load_config", return_value={"prefer_gpu": False})
    def test_get_engine_runtime_status_reports_cpu_when_gpu_disabled(self, _mock_load_config):
        self.addCleanup(lambda: setattr(clip_embedding, "engine", None))
        clip_embedding.engine = None
        clip_embedding._GPU_PROBE_CACHE = None

        status = clip_embedding.get_engine_runtime_status()

        self.assertTrue(status["initialized"])
        self.assertEqual(status["backend"], "CPU")


if __name__ == "__main__":
    unittest.main()
