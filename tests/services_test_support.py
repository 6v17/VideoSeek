"""Shared helpers and import stubs for service-layer unit tests."""

import sys
import types

try:
    import cv2 as _real_cv2
except Exception:
    _real_cv2 = None

if _real_cv2 is not None:
    sys.modules["cv2"] = _real_cv2
else:
    cv2_module = sys.modules.setdefault("cv2", types.SimpleNamespace())
    cv2_module.VideoCapture = getattr(cv2_module, "VideoCapture", lambda *_args, **_kwargs: None)
    cv2_module.CAP_PROP_FRAME_COUNT = getattr(cv2_module, "CAP_PROP_FRAME_COUNT", 7)
    cv2_module.CAP_PROP_POS_MSEC = getattr(cv2_module, "CAP_PROP_POS_MSEC", 0)
    cv2_module.CAP_PROP_FPS = getattr(cv2_module, "CAP_PROP_FPS", 5)

try:
    import faiss as _real_faiss
    sys.modules["faiss"] = _real_faiss
except ImportError:
    faiss_module = types.SimpleNamespace()
    faiss_module.normalize_L2 = getattr(faiss_module, "normalize_L2", lambda *_args, **_kwargs: None)
    sys.modules["faiss"] = faiss_module


def _model_dirs_from_test_config(config=None):
    cfg = dict(config or {})
    return {
        "base_dir": cfg.get("base_dir", "source/profile"),
        "vector_dir": cfg.get("vector_dir", "source/vector"),
        "index_dir": cfg.get("index_dir", "source/index"),
    }
