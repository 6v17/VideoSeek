import os
import queue
import re as std_re
import sys
import threading
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


class _GraphOptimizationLevel:
    ORT_DISABLE_ALL = 0
    ORT_ENABLE_EXTENDED = 1
    ORT_ENABLE_ALL = 2


onnxruntime_stub = types.SimpleNamespace(
    SessionOptions=_SessionOptions,
    ExecutionMode=_ExecutionMode,
    GraphOptimizationLevel=_GraphOptimizationLevel,
    get_available_providers=lambda: ["CPUExecutionProvider"],
    InferenceSession=object,
)
sys.modules.setdefault("onnxruntime", onnxruntime_stub)

from src.core import clip_embedding


def _clip_schema_v2_config(**overrides):
    prefer_gpu = overrides.pop("prefer_gpu", True)
    cfg = {
        "schema_version": 2,
        "data_root": "D:/VideoSeekData",
        "meta_file": "D:/VideoSeekData/meta.json",
        "vector_dir": "D:/VideoSeekData/vector",
        "index_dir": "D:/VideoSeekData/index",
        "models": {
            "active_profile": "clip_onnx_default",
            "profiles": [
                {
                    "id": "clip_onnx_default",
                    "provider": "clip_onnx",
                    "runtime": {"prefer_gpu": prefer_gpu, "model_dir": "D:/models"},
                }
            ],
        },
    }
    cfg.update(overrides)
    return cfg


class ClipEmbeddingRuntimeTests(unittest.TestCase):
    def setUp(self):
        clip_embedding.reset_engine()

    def tearDown(self):
        clip_embedding.reset_engine()
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
        fake_session = FakeSession()
        engine.init_vision_batch_state(
            visual_session=fake_session,
            embedding_batch_size=16,
            image_size=224,
            using_gpu=False,
            backend_label="CPU",
            active_providers={"visual": ["CPUExecutionProvider"], "text": ["CPUExecutionProvider"]},
        )
        engine.model_paths = {"clip_visual.onnx": "D:/clip/clip_visual.onnx"}

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
        engine.init_vision_batch_state(
            visual_session=FailingGpuSession(),
            embedding_batch_size=16,
            image_size=224,
            using_gpu=True,
            backend_label="GPU",
            active_providers={"visual": ["DmlExecutionProvider"], "text": ["DmlExecutionProvider"]},
        )
        engine.model_paths = {"clip_visual.onnx": "D:/clip/clip_visual.onnx"}
        engine._feature_dim = 2

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
        self.assertEqual(options.graph_optimization_level, clip_embedding.ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED)
        self.assertEqual(options.inter_op_num_threads, 1)
        self.assertGreaterEqual(options.intra_op_num_threads, 1)
        self.assertLessEqual(options.intra_op_num_threads, 4)

    @patch.dict(os.environ, {"VIDEOSEEK_ORT_INTRA_OP_THREADS": "1"}, clear=False)
    def test_build_session_options_intra_threads_env_override(self):
        options = clip_embedding._build_session_options(prefer_gpu=True)
        self.assertEqual(options.intra_op_num_threads, 1)

    def test_detect_gpu_runtime_issue_reports_missing_directml_provider(self):
        with (
            patch("src.core.clip_embedding._is_windows", return_value=True),
            patch("src.core.clip_embedding._is_windows_10_1903_or_newer", return_value=True),
            patch("src.core.clip_embedding._is_directml_provider_available", return_value=False),
        ):
            issue = clip_embedding.detect_gpu_runtime_issue()

        self.assertEqual(issue, "directml")

    def test_build_gpu_runtime_diagnostics_reports_missing_directml_provider(self):
        with (
            patch("src.core.clip_embedding._is_windows", return_value=True),
            patch("src.core.clip_embedding._is_windows_10_1903_or_newer", return_value=True),
            patch("src.core.clip_embedding._get_windows_build_number", return_value=22631),
            patch("src.core.clip_embedding._is_directml_provider_available", return_value=False),
            patch("src.core.clip_embedding._get_available_provider_names", return_value=["CPUExecutionProvider"]),
        ):
            diagnostics = clip_embedding._build_gpu_runtime_diagnostics()

        self.assertEqual(diagnostics["issue"], "directml")
        self.assertEqual(diagnostics["available_providers"], ["CPUExecutionProvider"])
        self.assertEqual(diagnostics["windows_build"], None)

    def test_detect_gpu_runtime_issue_reports_missing_directx_runtime(self):
        with (
            patch("src.core.clip_embedding._is_windows", return_value=True),
            patch("src.core.clip_embedding._is_windows_10_1903_or_newer", return_value=True),
            patch("src.core.clip_embedding._is_directml_provider_available", return_value=True),
            patch("src.core.clip_embedding._can_load_windows_dll", return_value=False),
        ):
            issue = clip_embedding.detect_gpu_runtime_issue()

        self.assertEqual(issue, "directx")

    def test_build_gpu_runtime_diagnostics_reports_missing_runtime_dlls(self):
        def fake_can_load(name):
            return name.lower() == "d3d12.dll"

        with (
            patch("src.core.clip_embedding._is_windows", return_value=True),
            patch("src.core.clip_embedding._is_windows_10_1903_or_newer", return_value=True),
            patch("src.core.clip_embedding._get_windows_build_number", return_value=22631),
            patch("src.core.clip_embedding._is_directml_provider_available", return_value=True),
            patch("src.core.clip_embedding._get_available_provider_names", return_value=["DmlExecutionProvider", "CPUExecutionProvider"]),
            patch("src.core.clip_embedding._can_load_windows_dll", side_effect=fake_can_load),
        ):
            diagnostics = clip_embedding._build_gpu_runtime_diagnostics()

        self.assertEqual(diagnostics["issue"], "directx")
        self.assertEqual(diagnostics["missing_dlls"], ["DirectML.dll"])
        self.assertIn("d3d12.dll", diagnostics["loaded_dlls"])

    def test_build_gpu_runtime_diagnostics_reports_missing_msvc_runtime_dlls(self):
        def fake_can_load(name):
            return name in {"DirectML.dll", "d3d12.dll", "vcruntime140.dll"}

        with (
            patch("src.core.clip_embedding._is_windows", return_value=True),
            patch("src.core.clip_embedding._is_windows_10_1903_or_newer", return_value=True),
            patch("src.core.clip_embedding._get_windows_build_number", return_value=22631),
            patch("src.core.clip_embedding._is_directml_provider_available", return_value=True),
            patch("src.core.clip_embedding._get_available_provider_names", return_value=["DmlExecutionProvider", "CPUExecutionProvider"]),
            patch("src.core.clip_embedding._can_load_windows_dll", side_effect=fake_can_load),
        ):
            diagnostics = clip_embedding._build_gpu_runtime_diagnostics()

        self.assertEqual(diagnostics["issue"], "msvc")
        self.assertEqual(diagnostics["missing_msvc_dlls"], ["vcruntime140_1.dll", "msvcp140.dll"])

    @patch("src.core.clip_embedding.ensure_model_files", return_value={"clip_visual.onnx": "visual.onnx", "clip_text.onnx": "text.onnx"})
    @patch("src.core.clip_embedding.tokenize", return_value=np.zeros((1, 77), dtype=np.int32))
    @patch("src.core.clip_embedding._build_gpu_runtime_diagnostics")
    def test_run_isolated_gpu_probe_success_clears_failure_stage_fields(self, mock_diagnostics, _mock_tokenize, _mock_models):
        class FakeSession:
            def __init__(self, *_args, **_kwargs):
                pass

            def get_providers(self):
                return ["DmlExecutionProvider", "CPUExecutionProvider"]

            def run(self, *_args, **_kwargs):
                return [np.array([[1.0, 0.0]], dtype=np.float32)]

        mock_diagnostics.return_value = {
            "issue": "unknown",
            "available_providers": ["DmlExecutionProvider", "CPUExecutionProvider"],
            "windows_build": 22631,
        }

        with patch.object(clip_embedding.ort, "InferenceSession", FakeSession, create=True):
            payload = clip_embedding._run_isolated_gpu_probe()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["issue"], "")
        self.assertNotIn("probe_stage", payload["diagnostics"])
        self.assertNotIn("failure_kind", payload["diagnostics"])
        self.assertNotIn("probe_exception_type", payload["diagnostics"])
        self.assertNotIn("probe_exception_message", payload["diagnostics"])
        self.assertEqual(payload["diagnostics"]["available_providers"], ["DmlExecutionProvider", "CPUExecutionProvider"])

    @patch("src.core.clip_embedding.load_config", return_value=_clip_schema_v2_config())
    @patch("src.core.clip_embedding._run_gpu_runtime_probe_once", return_value={"ok": False, "issue": "directx", "detail": "probe crashed"})
    def test_prepare_inference_runtime_falls_back_to_cpu_when_probe_fails(self, _mock_probe, _mock_load_config):
        status = clip_embedding.prepare_inference_runtime(prefer_gpu=True)

        self.assertFalse(status["effective_prefer_gpu"])
        self.assertEqual(status["issue"], "directx")
        self.assertIn("probe crashed", status["warning"])
        self.assertEqual(status["diagnostics"], {})

    @patch("src.core.clip_embedding.load_config", return_value=_clip_schema_v2_config())
    @patch("src.core.clip_embedding._run_gpu_runtime_probe_once", return_value={"ok": False, "issue": "unknown", "detail": "GPU runtime probe exited with code 1."})
    def test_prepare_inference_runtime_falls_back_to_cpu_when_probe_issue_is_unknown(self, _mock_probe, _mock_load_config):
        status = clip_embedding.prepare_inference_runtime(prefer_gpu=True)

        self.assertFalse(status["effective_prefer_gpu"])
        self.assertEqual(status["issue"], "unknown")
        self.assertIn("fell back to CPU", status["warning"])

    @patch(
        "src.core.clip_embedding.load_config",
        return_value=_clip_schema_v2_config(gpu_probe_unknown_keep_gpu=True),
    )
    @patch("src.core.clip_embedding._run_gpu_runtime_probe_once", return_value={"ok": False, "issue": "unknown", "detail": "GPU runtime probe exited with code 1."})
    def test_prepare_inference_runtime_keeps_gpu_for_unknown_issue_when_opted_in(self, _mock_probe, _mock_load_config):
        status = clip_embedding.prepare_inference_runtime(prefer_gpu=True)

        self.assertTrue(status["effective_prefer_gpu"])
        self.assertEqual(status["issue"], "unknown")
        self.assertIn("inconclusive", status["warning"])

    @patch("src.core.clip_embedding.load_config", return_value=_clip_schema_v2_config())
    @patch("src.core.clip_embedding._run_gpu_runtime_probe_once", return_value={"ok": False, "issue": "probe_timeout", "detail": "probe timed out", "diagnostics": {"failure_kind": "probe_timeout"}})
    def test_prepare_inference_runtime_keeps_gpu_when_probe_is_inconclusive(self, _mock_probe, _mock_load_config):
        status = clip_embedding.prepare_inference_runtime(prefer_gpu=True)

        self.assertTrue(status["effective_prefer_gpu"])
        self.assertEqual(status["issue"], "probe_timeout")
        self.assertIn("inconclusive", status["warning"])
        self.assertIn("probe timed out", status["warning"])
        self.assertEqual(status["diagnostics"]["failure_kind"], "probe_timeout")

    @patch("src.core.clip_embedding.load_config", return_value=_clip_schema_v2_config())
    @patch("src.core.clip_embedding._run_gpu_runtime_probe_once", return_value={"ok": True, "issue": "", "detail": ""})
    def test_prepare_inference_runtime_keeps_gpu_when_probe_succeeds(self, _mock_probe, _mock_load_config):
        status = clip_embedding.prepare_inference_runtime(prefer_gpu=True)

        self.assertTrue(status["effective_prefer_gpu"])
        self.assertEqual(status["warning"], "")
        self.assertEqual(status["diagnostics"], {})

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

    @patch("src.core.clip_embedding.load_config", return_value=_clip_schema_v2_config())
    @patch("src.core.clip_embedding._run_isolated_gpu_probe", return_value={"ok": False, "issue": "directx", "detail": "broken"})
    @patch("builtins.print")
    def test_gpu_probe_cli_main_returns_failure_exit_code(self, mock_print, _mock_probe, _mock_load_config):
        exit_code = clip_embedding.gpu_probe_cli_main()

        self.assertEqual(exit_code, 1)
        mock_print.assert_called_once()

    @patch("src.core.clip_embedding.load_config", return_value=_clip_schema_v2_config())
    def test_get_engine_runtime_status_uses_probe_cache_before_engine_init(self, _mock_load_config):
        clip_embedding._GPU_PROBE_CACHE = {"ok": True, "issue": "", "detail": "", "diagnostics": {"active_providers": ["DmlExecutionProvider"]}}
        self.addCleanup(lambda: setattr(clip_embedding, "_GPU_PROBE_CACHE", None))
        self.addCleanup(lambda: setattr(clip_embedding, "engine", None))
        clip_embedding.engine = None

        status = clip_embedding.get_engine_runtime_status()

        self.assertTrue(status["initialized"])
        self.assertEqual(status["backend"], "GPU")
        self.assertEqual(status["diagnostics"]["active_providers"], ["DmlExecutionProvider"])

    @patch("src.core.clip_embedding.load_config", return_value=_clip_schema_v2_config())
    def test_get_engine_runtime_status_keeps_gpu_for_inconclusive_probe_cache(self, _mock_load_config):
        clip_embedding._GPU_PROBE_CACHE = {"ok": False, "issue": "probe_timeout", "detail": "probe timed out", "diagnostics": {"failure_kind": "probe_timeout"}}
        self.addCleanup(lambda: setattr(clip_embedding, "_GPU_PROBE_CACHE", None))
        self.addCleanup(lambda: setattr(clip_embedding, "engine", None))
        clip_embedding.engine = None

        status = clip_embedding.get_engine_runtime_status()

        self.assertTrue(status["initialized"])
        self.assertEqual(status["backend"], "GPU")
        self.assertEqual(status["issue"], "probe_timeout")
        self.assertIn("inconclusive", status["warning"])
        self.assertEqual(status["diagnostics"]["failure_kind"], "probe_timeout")

    @patch("src.core.clip_embedding.load_config", return_value=_clip_schema_v2_config(prefer_gpu=False))
    def test_get_engine_runtime_status_reports_cpu_when_gpu_disabled(self, _mock_load_config):
        self.addCleanup(lambda: setattr(clip_embedding, "engine", None))
        clip_embedding.engine = None
        clip_embedding._GPU_PROBE_CACHE = None

        status = clip_embedding.get_engine_runtime_status()

        self.assertTrue(status["initialized"])
        self.assertEqual(status["backend"], "CPU")

    @patch(
        "src.core.clip_embedding.chunk_config_payload",
        return_value={
            "similarity_threshold": 0.85,
            "max_chunk_duration": 5.0,
            "min_chunk_size": 2,
            "similarity_mode": "chunk",
        },
    )
    @patch("src.core.clip_embedding.get_active_embedding_spec", return_value={})
    @patch("src.core.clip_embedding.load_config", return_value=_clip_schema_v2_config(prefer_gpu=False))
    @patch("src.core.clip_embedding._estimate_index_frame_total", return_value=5)
    @patch("src.core.clip_embedding.free_memory")
    @patch("src.core.clip_embedding.create_clip_index")
    @patch("src.core.clip_embedding.ensure_folder_exists")
    @patch("src.core.clip_embedding.save_vector_payload")
    @patch("src.core.clip_embedding.stream_frames_with_ffmpeg")
    @patch("src.core.clip_embedding.get_engine")
    def test_generate_vectors_reader_thread_batches_match_stream(
        self,
        mock_get_engine,
        mock_stream,
        mock_save,
        mock_ensure,
        mock_create,
        mock_free,
        mock_estimate,
        mock_load_cfg,
        mock_spec,
        mock_chunk_cfg,
    ):
        batch_lengths = []

        def fake_stream(_path, **_kwargs):
            for i in range(5):
                yield (np.zeros((224, 224, 3), dtype=np.uint8), float(i))

        mock_stream.side_effect = fake_stream

        class DummyEngine:
            embedding_batch_size = 2

            def encode_images(self, batch):
                batch_lengths.append(len(batch))
                return np.zeros((len(batch), 4), dtype=np.float32)

        mock_get_engine.return_value = DummyEngine()
        mock_create.return_value = object()
        clip_embedding.reset_engine()
        try:
            vectors, ts, _index = clip_embedding.generate_vectors_and_index_for_video(
                "D:/v.mp4", "vid1", "D:/idx", "D:/vec"
            )
        finally:
            clip_embedding.reset_engine()

        self.assertEqual(batch_lengths, [2, 2, 1])
        self.assertEqual(len(vectors), 5)
        self.assertEqual(len(ts), 5)

    @patch("src.core.clip_embedding.stream_frames_with_ffmpeg")
    def test_indexing_frame_reader_user_stop_is_not_recorded_as_failure(self, mock_stream):
        import src.core.clip_embedding as clip_embedding

        mock_stream.side_effect = InterruptedError("Frame extraction stopped")
        frame_queue = queue.Queue()
        stop_event = threading.Event()
        reader_error = []

        clip_embedding._run_indexing_frame_reader(
            "D:/v.mp4",
            frame_queue,
            stop_event,
            reader_error,
            {},
        )

        self.assertEqual(reader_error, [])
        self.assertIsNone(frame_queue.get(timeout=1.0))

    @patch("src.core.clip_embedding.build_inference_engine")
    @patch("src.core.clip_embedding.get_active_model_profile")
    @patch("src.core.clip_embedding.load_config", return_value=_clip_schema_v2_config())
    def test_get_engine_rebuilds_when_active_provider_changes(
        self,
        _mock_load_config,
        mock_get_profile,
        mock_build_engine,
    ):
        class DummyEngine:
            provider_id = "clip_onnx"
            model_profile_id = "clip_onnx_default"
            visual_session = object()
            backend_label = "CPU"

        first = DummyEngine()
        second = DummyEngine()
        second.provider_id = "siglip2_onnx"
        second.model_profile_id = "siglip2_default"
        mock_build_engine.side_effect = [first, second]
        mock_get_profile.side_effect = [
            {"id": "clip_onnx_default", "provider": "clip_onnx"},
            {"id": "siglip2_default", "provider": "siglip2_onnx"},
        ]

        got_first = clip_embedding.get_engine()
        got_second = clip_embedding.get_engine()

        self.assertIs(got_first, first)
        self.assertIs(got_second, second)
        self.assertEqual(mock_build_engine.call_count, 2)


if __name__ == "__main__":
    unittest.main()
