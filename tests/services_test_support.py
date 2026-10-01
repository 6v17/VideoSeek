"""Shared helpers and import stubs for service-layer unit tests."""

import os
import sys
import tempfile
import types

# Hard isolation: Lance/storage mutation must never touch real AppData VideoSeek.
os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")

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
    # Defaults stay under system temp so helpers never create repo-relative dirs.
    root = os.path.join(tempfile.gettempdir(), "videoseek_pytest_assets")
    return {
        "base_dir": cfg.get("base_dir", os.path.join(root, "profile")),
        "vector_dir": cfg.get("vector_dir", os.path.join(root, "vector")),
        "index_dir": cfg.get("index_dir", os.path.join(root, "index")),
    }
