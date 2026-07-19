"""RapidOCR (ONNX) wrapper for hard-subtitle recognition.

Models are loaded from an imported understanding component directory
(``vision/ocr/rapidocr-zh``). Inference uses onnxruntime; on Windows this can
include DirectML when the RapidOCR backend / ORT build supports it.

RapidOCR's real batching is recognition-side ``rec_batch_num`` (multiple text
boxes inside one image). Detection is per-image; VideoSeek overlaps decode with
OCR instead of stacking frames.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import numpy as np

from src.app.logging_utils import get_logger

logger = get_logger("subtitle_ocr.rapidocr")

OCR_COMPONENT_ID = "vision/ocr/rapidocr-zh"
_ENGINE_LOCK = threading.RLock()
_ENGINE_CACHE: dict[str, Any] = {}


def is_rapidocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return True
    except ImportError:
        try:
            import rapidocr  # noqa: F401

            return True
        except ImportError:
            return False


def resolve_rapidocr_model_dir(*, config=None, model_dir: str | None = None) -> str | None:
    """Return installed component dir if det/rec ONNX files exist."""
    from src.services.understanding_paths import get_component_dir

    component_dir = get_component_dir(OCR_COMPONENT_ID, model_dir=model_dir)
    if not os.path.isdir(component_dir):
        return None
    det = _find_model_file(component_dir, ("det.onnx", "ch_PP-OCRv4_det_infer.onnx", "ch_PP-OCRv3_det_infer.onnx"))
    rec = _find_model_file(component_dir, ("rec.onnx", "ch_PP-OCRv4_rec_infer.onnx", "ch_PP-OCRv3_rec_infer.onnx"))
    if det and rec:
        return component_dir
    return None


def _find_model_file(root: str, names: tuple[str, ...]) -> str | None:
    for name in names:
        path = os.path.join(root, name)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    # allow one-level nesting (models/, onnx/)
    try:
        for child in os.listdir(root):
            child_dir = os.path.join(root, child)
            if not os.path.isdir(child_dir):
                continue
            for name in names:
                path = os.path.join(child_dir, name)
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    return path
    except OSError:
        pass
    return None


def _model_paths(component_dir: str) -> dict[str, str]:
    det = _find_model_file(component_dir, ("det.onnx", "ch_PP-OCRv4_det_infer.onnx", "ch_PP-OCRv3_det_infer.onnx"))
    rec = _find_model_file(component_dir, ("rec.onnx", "ch_PP-OCRv4_rec_infer.onnx", "ch_PP-OCRv3_rec_infer.onnx"))
    cls = _find_model_file(component_dir, ("cls.onnx", "ch_ppocr_mobile_v2.0_cls_infer.onnx"))
    keys = _find_model_file(component_dir, ("dict.txt", "ppocr_keys_v1.txt", "rec_dict.txt"))
    if not det or not rec:
        raise FileNotFoundError(f"RapidOCR det/rec ONNX missing under {component_dir}")
    payload = {"det_model_path": det, "rec_model_path": rec}
    if cls:
        payload["cls_model_path"] = cls
    if keys:
        payload["rec_keys_path"] = keys
    return payload


def get_rapidocr_engine(*, config=None, model_dir: str | None = None, prefer_gpu: bool = True):
    """Cached RapidOCR instance bound to the imported understanding component."""
    component_dir = resolve_rapidocr_model_dir(config=config, model_dir=model_dir)
    if not component_dir:
        raise FileNotFoundError(
            f"RapidOCR model not imported: {OCR_COMPONENT_ID}. "
            "Import the understanding zip (Understanding / Settings → Import Model)."
        )
    if not is_rapidocr_available():
        raise RuntimeError("rapidocr-onnxruntime (or rapidocr) is not installed")

    cache_key = f"{os.path.normpath(component_dir)}|gpu={int(bool(prefer_gpu))}"
    with _ENGINE_LOCK:
        cached = _ENGINE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        paths = _model_paths(component_dir)
        engine = _build_engine(paths, prefer_gpu=prefer_gpu)
        _ENGINE_CACHE[cache_key] = engine
        logger.info("RapidOCR ready: dir=%s prefer_gpu=%s", component_dir, prefer_gpu)
        return engine


def _build_engine(paths: dict[str, str], *, prefer_gpu: bool):
    try:
        from rapidocr_onnxruntime import RapidOCR

        kwargs: dict[str, Any] = dict(paths)
        # Hard-subtitles are upright — skip angle classifier (big win).
        kwargs["use_cls"] = False
        kwargs["max_side_len"] = 960
        kwargs["det_limit_side_len"] = 640
        # RapidOCR native batch: recognize multiple boxes in one image together.
        kwargs["rec_batch_num"] = 6
        try:
            import onnxruntime as ort

            available = set(ort.get_available_providers())
            if prefer_gpu and "CUDAExecutionProvider" in available:
                kwargs["det_use_cuda"] = True
                kwargs["cls_use_cuda"] = True
                kwargs["rec_use_cuda"] = True
            # VideoSeek Windows builds ship onnxruntime-directml; RapidOCR defaults
            # leave use_dml=false and silently run CPU — force it on when present.
            if prefer_gpu and "DmlExecutionProvider" in available:
                kwargs["det_use_dml"] = True
                kwargs["cls_use_dml"] = True
                kwargs["rec_use_dml"] = True
                logger.info("RapidOCR DirectML enabled (providers=%s)", sorted(available))
        except Exception as exc:
            logger.warning("RapidOCR provider probe failed: %s", exc)
        return RapidOCR(**kwargs)
    except ImportError:
        from rapidocr import RapidOCR

        return RapidOCR(
            params={
                "Det.model_path": paths["det_model_path"],
                "Rec.model_path": paths["rec_model_path"],
                **(
                    {"Cls.model_path": paths["cls_model_path"]}
                    if paths.get("cls_model_path")
                    else {}
                ),
            }
        )


def clear_rapidocr_engine_cache() -> None:
    with _ENGINE_LOCK:
        _ENGINE_CACHE.clear()


def ocr_image_bgr(frame_bgr: np.ndarray, *, config=None, prefer_gpu: bool = True) -> list[dict[str, Any]]:
    """Run OCR on one BGR frame. Returns ``[{text, score}, ...]`` top-to-bottom-ish."""
    if frame_bgr is None or not isinstance(frame_bgr, np.ndarray) or frame_bgr.size <= 0:
        return []
    engine = get_rapidocr_engine(config=config, prefer_gpu=prefer_gpu)
    # Hard-subs: skip cls at call-site too (engine may still have it loaded).
    try:
        result = engine(frame_bgr, use_cls=False)
    except TypeError:
        result = engine(frame_bgr)
    rows = result[0] if isinstance(result, tuple) else result
    if not rows:
        return []
    out: list[dict[str, Any]] = []
    for item in rows:
        # Formats: [box, text, score] or dict-like
        text = ""
        score = 0.0
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            text = str(item[1] if not isinstance(item[1], (int, float)) else item[0] or "").strip()
            # common: (box, text, score)
            if len(item) >= 3 and isinstance(item[1], str):
                text = str(item[1]).strip()
                try:
                    score = float(item[2])
                except (TypeError, ValueError):
                    score = 0.0
            elif isinstance(item[0], str):
                text = str(item[0]).strip()
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("transcription") or "").strip()
            try:
                score = float(item.get("score") or item.get("confidence") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
        if not text:
            continue
        out.append({"text": text, "score": score})
    return out


def ocr_frame_to_line(
    frame_bgr: np.ndarray,
    *,
    config=None,
    prefer_gpu: bool = True,
    min_score: float = 0.45,
    join_with: str = " ",
) -> str:
    parts = [
        row["text"]
        for row in ocr_image_bgr(frame_bgr, config=config, prefer_gpu=prefer_gpu)
        if float(row.get("score") or 0.0) >= float(min_score) or not row.get("score")
    ]
    return join_with.join(parts).strip()
