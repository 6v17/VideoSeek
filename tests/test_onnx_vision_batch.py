import os
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np


class _SessionOptions:
    def __init__(self):
        self.enable_mem_pattern = True
        self.execution_mode = "parallel"


class _ExecutionMode:
    ORT_SEQUENTIAL = "sequential"


class _GraphOptimizationLevel:
    ORT_DISABLE_ALL = 0
    ORT_ENABLE_EXTENDED = 1


sys.modules.setdefault(
    "onnxruntime",
    types.SimpleNamespace(
        SessionOptions=_SessionOptions,
        ExecutionMode=_ExecutionMode,
        GraphOptimizationLevel=_GraphOptimizationLevel,
        get_available_providers=lambda: ["CPUExecutionProvider"],
        InferenceSession=object,
    ),
)

from src.core import onnx_vision_engine as ove
from src.core.clip_embedding import resolve_index_frame_queue_size
from src.core.onnx_vision_engine import OnnxVisionBatchMixin


class _SpyLock:
    def __init__(self, events):
        self._events = events

    def __enter__(self):
        self._events.append("lock")
        return self

    def __exit__(self, exc_type, exc, tb):
        self._events.append("unlock")
        return False


class OnnxVisionBatchUnlockTests(unittest.TestCase):
    def _build_engine(self, *, batch_size=4, feature_dim=2, events=None):
        events = [] if events is None else events

        class Engine(OnnxVisionBatchMixin):
            def preprocess_into(self, img_bgr, out_chw):
                events.append("preprocess")
                out_chw.fill(0.25)

            def visual_input_name(self):
                return "input"

        engine = Engine.__new__(Engine)
        engine.init_vision_batch_state(
            visual_session=object(),
            embedding_batch_size=batch_size,
            image_size=8,
            using_gpu=False,
            backend_label="CPU",
            active_providers={"visual": ["CPUExecutionProvider"]},
        )
        engine._feature_dim = feature_dim

        def track_run(blob):
            events.append(("run", int(blob.shape[0])))
            return np.ones((blob.shape[0], feature_dim), dtype=np.float32)

        engine._run_visual_batch = track_run
        return engine, events

    def test_preprocess_happens_before_inference_lock(self):
        events = []
        engine, events = self._build_engine(batch_size=4, events=events)
        frames = [np.zeros((8, 8, 3), dtype=np.uint8) for _ in range(5)]

        with patch.object(ove, "INFERENCE_LOCK", _SpyLock(events)):
            vectors = engine.encode_images(frames)

        self.assertEqual(vectors.shape, (5, 2))
        preprocess_idxs = [i for i, item in enumerate(events) if item == "preprocess"]
        lock_idx = events.index("lock")
        self.assertEqual(len(preprocess_idxs), 5)
        self.assertTrue(all(idx < lock_idx for idx in preprocess_idxs))
        run_events = [item for item in events if isinstance(item, tuple) and item[0] == "run"]
        self.assertEqual(run_events, [("run", 4), ("run", 1)])
        self.assertTrue(all(events.index(item) > lock_idx for item in run_events))

    def test_preprocess_frames_to_batches_shapes(self):
        engine, _events = self._build_engine(batch_size=3)
        frames = [np.zeros((8, 8, 3), dtype=np.uint8) for _ in range(7)]
        batches = engine._preprocess_frames_to_batches(frames)
        self.assertEqual([int(batch.shape[0]) for batch in batches], [3, 3, 1])
        for batch in batches:
            self.assertEqual(batch.shape[1:], (3, 8, 8))
            self.assertEqual(batch.dtype, np.float32)

    def test_encode_images_empty_returns_zero_rows(self):
        engine, _events = self._build_engine()
        empty = engine.encode_images([])
        self.assertEqual(empty.shape, (0, 2))


class IndexFrameQueueSizeTests(unittest.TestCase):
    def test_default_queue_is_max_64_or_batch_times_8(self):
        with patch.dict(os.environ, {"VIDEOSEEK_INDEX_FRAME_QUEUE": ""}, clear=False):
            self.assertEqual(resolve_index_frame_queue_size(16), 128)
            self.assertEqual(resolve_index_frame_queue_size(4), 64)
            self.assertEqual(resolve_index_frame_queue_size(1), 64)

    @patch.dict(os.environ, {"VIDEOSEEK_INDEX_FRAME_QUEUE": "40"}, clear=False)
    def test_env_override(self):
        self.assertEqual(resolve_index_frame_queue_size(16), 40)

    @patch.dict(os.environ, {"VIDEOSEEK_INDEX_FRAME_QUEUE": "bad"}, clear=False)
    def test_invalid_env_falls_back(self):
        self.assertEqual(resolve_index_frame_queue_size(8), 64)


if __name__ == "__main__":
    unittest.main()
