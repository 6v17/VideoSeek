import numpy as np
import pytest

from src.core import ort_cuda_io_binding as binding
from src.core.onnx_vision_engine import OnnxVisionBatchMixin


class _FakeIoBinding:
    def __init__(self):
        self.inputs = {}
        self.bound_outputs = []
        self._outputs = None

    def bind_cpu_input(self, name, arr):
        self.inputs[name] = arr

    def bind_input(self, name, device_type, device_id=0, element_type=None, shape=None, buffer_ptr=None):
        self.inputs[name] = (device_type, device_id, element_type, shape, buffer_ptr)

    def bind_output(self, name, device_type, device_id=0, element_type=None, shape=None, buffer_ptr=None):
        self.bound_outputs.append((name, device_type, device_id, element_type, shape))

    def copy_outputs_to_cpu(self):
        if self._outputs is not None:
            return self._outputs
        batch = int(self.inputs["pixel_values"].shape[0])
        return [np.full((batch, 4), 3.0, dtype=np.float32)]


class _FakeCudaSession:
    def __init__(self):
        self.run_calls = 0
        self.io_binding_calls = 0
        self.last_io_binding = None

    def get_providers(self):
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]

    def get_outputs(self):
        meta = type("Meta", (), {"name": "image_embeds", "shape": ["batch", 4], "type": "tensor(float)"})()
        return [meta]

    def io_binding(self):
        self.io_binding_calls += 1
        binding = _FakeIoBinding()
        self.last_io_binding = binding
        return binding

    def run(self, _outputs, _inputs):
        self.run_calls += 1
        batch = int(_inputs["pixel_values"].shape[0])
        return [np.full((batch, 4), 2.0, dtype=np.float32)]

    def run_with_iobinding(self, io_binding):
        self.run_calls += 1
        batch = int(io_binding.inputs["pixel_values"].shape[0]) if hasattr(io_binding.inputs["pixel_values"], "shape") else int(io_binding.inputs["pixel_values"][3][0])
        if isinstance(io_binding.inputs.get("pixel_values"), tuple):
            batch = int(io_binding.inputs["pixel_values"][3][0])
        io_binding._outputs = [np.full((batch, 4), 3.0, dtype=np.float32)]


class _VisionEngineStub(OnnxVisionBatchMixin):
    def visual_model_path(self):
        return r"D:\models\chinese_clip_image.onnx"

    def visual_input_name(self):
        return "pixel_values"

    def preprocess_into(self, img_bgr, out_chw):
        out_chw[:] = 0.0

    def extract_visual_features(self, outputs):
        return outputs[0].astype(np.float32)


def test_cuda_io_binding_disabled_for_dml_default(monkeypatch):
    monkeypatch.delenv("VIDEOSEEK_INFERENCE_EP", raising=False)
    monkeypatch.delenv("VIDEOSEEK_CUDA_IO_BINDING", raising=False)
    assert not binding.is_cuda_io_binding_enabled()


def test_cuda_io_binding_enabled_in_cuda_mode(monkeypatch):
    monkeypatch.setenv("VIDEOSEEK_INFERENCE_EP", "cuda")
    assert binding.is_cuda_io_binding_enabled()


def test_io_binding_runner_defers_output_binding(monkeypatch):
    monkeypatch.setenv("VIDEOSEEK_INFERENCE_EP", "cuda")
    session = _FakeCudaSession()
    runner = binding.create_cuda_visual_io_binding_runner(session, input_name="pixel_values")

    assert runner is not None
    assert session.io_binding_calls == 0

    blob = np.zeros((16, 3, 224, 224), dtype=np.float32)
    outputs = runner.run(blob)

    assert session.io_binding_calls == 1
    assert outputs[0].shape == (16, 4)
    assert session.last_io_binding.bound_outputs == [
        ("image_embeds", "cpu", 0, np.float32, (16, 4)),
    ]


def test_io_binding_runner_accepts_gpu_input(monkeypatch):
    monkeypatch.setenv("VIDEOSEEK_INFERENCE_EP", "cuda")
    session = _FakeCudaSession()
    runner = binding.create_cuda_visual_io_binding_runner(session, input_name="pixel_values")
    outputs = runner.run_gpu_input(123456789, (8, 3, 224, 224))

    assert outputs[0].shape == (8, 4)
    assert session.last_io_binding.inputs["pixel_values"][0] == "cuda"
    assert session.last_io_binding.inputs["pixel_values"][4] == 123456789


def test_resolve_output_shape_uses_runtime_batch():
    meta = type("Meta", (), {"name": "image_features", "shape": ["batch", 512], "type": "tensor(float)"})()
    assert binding._resolve_output_shape(meta, 16) == (16, 512)


def test_visual_batch_uses_io_binding_on_cuda(monkeypatch):
    monkeypatch.setenv("VIDEOSEEK_INFERENCE_EP", "cuda")
    engine = _VisionEngineStub()
    session = _FakeCudaSession()
    engine.init_vision_batch_state(
        visual_session=session,
        embedding_batch_size=4,
        using_gpu=True,
        backend_label="GPU",
        active_providers={"visual": ["CUDAExecutionProvider"]},
    )
    engine._feature_dim = 4

    blob = np.zeros((2, 3, 224, 224), dtype=np.float32)
    feat = engine._run_visual_batch_once(blob)

    assert feat.shape == (2, 4)
    assert session.io_binding_calls >= 1
    assert session.run_calls >= 1
    assert engine._cuda_io_binding_disabled is False


def test_visual_batch_falls_back_when_io_binding_batch_mismatch(monkeypatch):
    monkeypatch.setenv("VIDEOSEEK_INFERENCE_EP", "cuda")

    class _PinnedBatchOneSession(_FakeCudaSession):
        def run_with_iobinding(self, io_binding):
            self.run_calls += 1
            io_binding._outputs = [np.full((1, 4), 3.0, dtype=np.float32)]

    engine = _VisionEngineStub()
    session = _PinnedBatchOneSession()
    engine.init_vision_batch_state(
        visual_session=session,
        embedding_batch_size=16,
        using_gpu=True,
        backend_label="GPU",
        active_providers={"visual": ["CUDAExecutionProvider"]},
    )
    engine._feature_dim = 4

    blob = np.zeros((16, 3, 224, 224), dtype=np.float32)
    feat = engine._run_visual_batch_once(blob)

    assert feat.shape == (16, 4)
    assert engine._cuda_io_binding_disabled is True
    assert session.run_calls >= 2


def test_visual_batch_falls_back_to_session_run(monkeypatch):
    monkeypatch.setenv("VIDEOSEEK_INFERENCE_EP", "cuda")

    class _BrokenBindingSession(_FakeCudaSession):
        def run_with_iobinding(self, _io_binding):
            raise RuntimeError("io binding unsupported")

    engine = _VisionEngineStub()
    session = _BrokenBindingSession()
    engine.init_vision_batch_state(
        visual_session=session,
        embedding_batch_size=4,
        using_gpu=True,
        backend_label="GPU",
        active_providers={"visual": ["CUDAExecutionProvider"]},
    )
    engine._feature_dim = 4

    blob = np.zeros((1, 3, 224, 224), dtype=np.float32)
    feat = engine._run_visual_batch_once(blob)

    assert feat.shape == (1, 4)
    assert engine._cuda_io_binding_disabled is True
    assert session.run_calls >= 1
