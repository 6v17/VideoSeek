import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

import numpy as np


def _fake_cvt_color(img, _code):
    return np.asarray(img)


_cv2_stub = types.SimpleNamespace(
    COLOR_BGR2RGB=1,
    INTER_AREA=3,
    INTER_LINEAR=1,
    cvtColor=_fake_cvt_color,
    resize=lambda img, size, interpolation=None: img,
)
sys.modules.setdefault("cv2", _cv2_stub)
sys.modules.setdefault("faiss", types.SimpleNamespace())


class _SessionOptions:
    def __init__(self):
        self.enable_mem_pattern = True
        self.execution_mode = "parallel"


class _ExecutionMode:
    ORT_SEQUENTIAL = "sequential"


class _GraphOptimizationLevel:
    ORT_DISABLE_ALL = 0
    ORT_ENABLE_EXTENDED = 1


if "onnxruntime" not in sys.modules:
    sys.modules["onnxruntime"] = types.SimpleNamespace(
        SessionOptions=_SessionOptions,
        ExecutionMode=_ExecutionMode,
        GraphOptimizationLevel=_GraphOptimizationLevel,
        get_available_providers=lambda: ["CPUExecutionProvider"],
        InferenceSession=MagicMock,
    )


class SigLIPEncodeImagesTests(unittest.TestCase):
    def _build_engine(self, *, batch_size=4, feature_dim=768):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: self._cleanup_dir(tmpdir))
        for name in ("vision_model.onnx", "text_model.onnx", "tokenizer.json"):
            with open(os.path.join(tmpdir, name), "wb") as handle:
                handle.write(b"x")

        run_calls = []

        def fake_run(_outputs, feed_dict):
            blob = feed_dict["pixel_values"]
            run_calls.append(int(blob.shape[0]))
            return [np.ones((blob.shape[0], feature_dim), dtype=np.float32)]

        vision_session = MagicMock()
        vision_session.get_providers.return_value = ["CPUExecutionProvider"]
        vision_session.get_inputs.return_value = [MagicMock(name="pixel_values")]
        vision_session.run.side_effect = fake_run

        text_session = MagicMock()
        text_session.get_providers.return_value = ["CPUExecutionProvider"]

        with patch("src.core.siglip_provider.ort.InferenceSession", side_effect=[vision_session, text_session]):
            with patch("src.core.siglip_provider.build_session_options", return_value=MagicMock()):
                with patch("src.core.siglip_provider.load_config", return_value={"embedding_batch_size": batch_size}):
                    with patch("src.core.siglip_provider.get_effective_prefer_gpu", return_value=False):
                        from src.core.siglip_provider import SigLIP2OnnxEngine

                        with patch.object(
                            SigLIP2OnnxEngine,
                            "_build_tokenizer",
                            return_value={"backend": "tokenizers", "instance": MagicMock()},
                        ):
                            engine = SigLIP2OnnxEngine(tmpdir)

        engine.vision_session = vision_session
        engine._vision_input_name = "pixel_values"
        engine._feature_dim = feature_dim
        return engine, run_calls

    @staticmethod
    def _cleanup_dir(path):
        for root, dirs, files in os.walk(path, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(path)

    def test_encode_images_runs_one_onnx_call_per_batch(self):
        engine, _run_calls = self._build_engine(batch_size=4)
        batch_sizes = []

        def track_batch(batch):
            batch_sizes.append(int(batch.shape[0]))
            return np.ones((batch.shape[0], 768), dtype=np.float32)

        engine._run_visual_batch = track_batch
        frames = [np.zeros((224, 224, 3), dtype=np.uint8) for _ in range(10)]

        vectors = engine.encode_images(frames)

        self.assertEqual(batch_sizes, [4, 4, 2])
        self.assertEqual(vectors.shape, (10, 768))

    def test_preprocess_skips_resize_for_224_frames(self):
        engine, _run_calls = self._build_engine(batch_size=2)
        out = np.empty((3, 224, 224), dtype=np.float32)
        frame = np.full((224, 224, 3), 127, dtype=np.uint8)

        with patch("src.core.siglip_provider.cv2.resize") as mock_resize:
            engine.preprocess_into(frame, out)

        mock_resize.assert_not_called()
        self.assertAlmostEqual(float(out[0, 0, 0]), -1.0 / 255.0, places=5)

    def test_run_visual_batch_splits_failed_batch_until_single_frame(self):
        from src.core.siglip_provider import SigLIP2OnnxEngine

        class FakeSession:
            def __init__(self):
                self.batch_sizes = []

            def run(self, _outputs, inputs):
                batch = inputs["pixel_values"]
                self.batch_sizes.append(int(batch.shape[0]))
                if batch.shape[0] > 1:
                    raise RuntimeError("temporary batch failure")
                return [np.array([[1.0, 0.0]], dtype=np.float32)]

        engine = SigLIP2OnnxEngine.__new__(SigLIP2OnnxEngine)
        engine.init_vision_batch_state(
            visual_session=FakeSession(),
            embedding_batch_size=16,
            image_size=224,
            using_gpu=False,
            backend_label="CPU",
            active_providers={"visual": ["CPUExecutionProvider"], "text": ["CPUExecutionProvider"]},
        )
        engine._vision_input_name = "pixel_values"
        engine._vision_path = "D:/siglip/vision_model.onnx"

        batch = [np.zeros((3, 224, 224), dtype=np.float32), np.zeros((3, 224, 224), dtype=np.float32)]
        result = engine._run_visual_batch(batch)

        self.assertEqual(result.shape, (2, 2))
        self.assertEqual(engine.visual_session.batch_sizes, [2, 1, 1])

    def test_run_visual_batch_falls_back_to_cpu_after_gpu_single_frame_failure(self):
        from src.core.siglip_provider import SigLIP2OnnxEngine

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

        engine = SigLIP2OnnxEngine.__new__(SigLIP2OnnxEngine)
        engine.init_vision_batch_state(
            visual_session=FailingGpuSession(),
            embedding_batch_size=16,
            image_size=224,
            using_gpu=True,
            backend_label="GPU",
            active_providers={"vision": ["DmlExecutionProvider"], "text": ["CPUExecutionProvider"]},
        )
        engine._vision_input_name = "pixel_values"
        engine._feature_dim = 2
        engine._vision_path = "D:/siglip/vision_model.onnx"

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


if __name__ == "__main__":
    unittest.main()
