import os
import re as std_re
import sys
import types
import unittest
from unittest.mock import patch

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
