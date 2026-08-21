"""RapidOCR (ONNX) wrapper for hard-subtitle recognition.

Models are loaded from an imported understanding component directory
(``vision/ocr/rapidocr-zh``). Inference uses onnxruntime; on Windows this can
include DirectML when the RapidOCR backend / ORT build supports it.

Optional multi-ROI stack batch: several subtitle ROIs are padded/stacked into
one image for a single RapidOCR pass, then split by Y bands. Ambiguous band
hits fall back to per-frame OCR (never guess neighboring frames).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from src.app.logging_utils import get_logger

logger = get_logger("subtitle_ocr.rapidocr")

OCR_COMPONENT_ID = "vision/ocr/rapidocr-zh"
_ENGINE_LOCK = threading.RLock()
_ENGINE_CACHE: dict[str, Any] = {}
_FORCE_CPU = False
_DEFAULT_BATCH_SIZE = 6
_MAX_BATCH_SIZE = 6
_STACK_GAP_PX = 48
_STACK_GAP_VALUE = 114
_BAND_EDGE_MARGIN_PX = 4
_ORT_FAIL_MARKERS = (
    "onnxruntime",
    "onnxruntimeerror",
    "dml",
    "directml",
    "out of memory",
    "failed to allocate",
    "device removed",
    "dxgi_error",
    "hbm",
)

# Nuitka/PyInstaller often ships .py but omits package data; keep a fallback copy.
_DEFAULT_RAPIDOCR_CONFIG_YAML = """Global:
    text_score: 0.5
    use_det: true
    use_cls: true
    use_rec: true
    print_verbose: false
    min_height: 30
    width_height_ratio: 8
    max_side_len: 2000
    min_side_len: 30
    return_word_box: false

    intra_op_num_threads: &intra_nums -1
    inter_op_num_threads: &inter_nums -1

Det:
    intra_op_num_threads: *intra_nums
    inter_op_num_threads: *inter_nums

    use_cuda: false
    use_dml: false

    model_path: models/ch_PP-OCRv4_det_infer.onnx

    limit_side_len: 736
    limit_type: min
    std: [ 0.5, 0.5, 0.5 ]
    mean: [ 0.5, 0.5, 0.5 ]

    thresh: 0.3
    box_thresh: 0.5
    max_candidates: 1000
    unclip_ratio: 1.6
    use_dilation: true
    score_mode: fast

Cls:
    intra_op_num_threads: *intra_nums
    inter_op_num_threads: *inter_nums

    use_cuda: false
    use_dml: false

    model_path: models/ch_ppocr_mobile_v2.0_cls_infer.onnx

    cls_image_shape: [3, 48, 192]
    cls_batch_num: 6
    cls_thresh: 0.9
    label_list: ['0', '180']

Rec:
    intra_op_num_threads: *intra_nums
    inter_op_num_threads: *inter_nums

    use_cuda: false
    use_dml: false

    model_path: models/ch_PP-OCRv4_rec_infer.onnx

    rec_img_shape: [3, 48, 320]
    rec_batch_num: 6
"""


def resolve_subtitle_ocr_batch_size(*, config=None) -> int:
    """How many subtitle ROIs to OCR in one stacked pass (1 = off)."""
    raw = os.environ.get("VIDEOSEEK_SUBTITLE_OCR_BATCH", "").strip()
    if raw:
        try:
            return max(1, min(_MAX_BATCH_SIZE, int(raw)))
        except ValueError:
            pass
    if config is not None:
        try:
            return max(1, min(_MAX_BATCH_SIZE, int(config.get("subtitle_ocr_batch_size", _DEFAULT_BATCH_SIZE))))
        except (TypeError, ValueError):
            return _DEFAULT_BATCH_SIZE
    try:
        from src.app.config import DEFAULT_CONFIG, load_config

        cfg = load_config()
        return max(
            1,
            min(
                _MAX_BATCH_SIZE,
                int(cfg.get("subtitle_ocr_batch_size", DEFAULT_CONFIG.get("subtitle_ocr_batch_size", _DEFAULT_BATCH_SIZE))),
            ),
        )
    except Exception:
        return _DEFAULT_BATCH_SIZE


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


def _iter_rapidocr_config_candidates() -> list[Path]:
    """Locations where packaged or installed RapidOCR config.yaml may live."""
    from src.infra.paths import get_app_data_dir, get_app_install_dir, get_resource_path

    candidates: list[Path] = []
    try:
        import rapidocr_onnxruntime

        pkg_file = Path(str(rapidocr_onnxruntime.__file__ or ""))
        if pkg_file.name:
            # Prefer non-resolved path first: short-path installs can resolve to a
            # different letter/name that does not contain package data.
            candidates.append(pkg_file.parent / "config.yaml")
            try:
                candidates.append(pkg_file.resolve().parent / "config.yaml")
            except OSError:
                pass
    except ImportError:
        pass

    install_dir = Path(get_app_install_dir())
    candidates.append(install_dir / "rapidocr_onnxruntime" / "config.yaml")
    for rel in (
        "rapidocr_onnxruntime/config.yaml",
        "resources/rapidocr_onnxruntime/config.yaml",
    ):
        try:
            candidates.append(Path(get_resource_path(rel)))
        except Exception:
            pass
    candidates.append(Path(get_app_data_dir()) / "rapidocr_onnxruntime" / "config.yaml")
    return candidates


def _write_rapidocr_config(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_RAPIDOCR_CONFIG_YAML, encoding="utf-8")
        return path.is_file() and path.stat().st_size > 0
    except OSError as exc:
        logger.warning("Failed to write RapidOCR config.yaml to %s: %s", path, exc)
        return False


def resolve_rapidocr_config_path() -> str:
    """Return a readable RapidOCR config.yaml, materializing one if packaging omitted it."""
    seen: set[str] = set()
    writable_targets: list[Path] = []
    for path in _iter_rapidocr_config_candidates():
        key = os.path.normcase(os.path.normpath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.is_file() and path.stat().st_size > 0:
                return str(path)
        except OSError:
            continue
        writable_targets.append(path)

    from src.infra.paths import get_app_data_dir

    fallback = Path(get_app_data_dir()) / "rapidocr_onnxruntime" / "config.yaml"
    for target in [fallback, *writable_targets]:
        if _write_rapidocr_config(target):
            logger.info(
                "Materialized RapidOCR config.yaml at %s (package data missing in install)",
                target,
            )
            return str(target)
    raise FileNotFoundError(
        "RapidOCR config.yaml is missing and could not be created. "
        "Reinstall VideoSeek or copy resources/rapidocr_onnxruntime/config.yaml beside the app."
    )


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

    use_gpu = _effective_prefer_gpu(prefer_gpu)
    cache_key = f"{os.path.normpath(component_dir)}|gpu={int(use_gpu)}"
    with _ENGINE_LOCK:
        cached = _ENGINE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        paths = _model_paths(component_dir)
        engine = _build_engine(paths, prefer_gpu=use_gpu)
        _ENGINE_CACHE[cache_key] = engine
        logger.info("RapidOCR ready: dir=%s prefer_gpu=%s", component_dir, use_gpu)
        return engine


def _build_engine(paths: dict[str, str], *, prefer_gpu: bool):
    try:
        from rapidocr_onnxruntime import RapidOCR

        kwargs: dict[str, Any] = dict(paths)
        kwargs["use_cls"] = False
        kwargs["max_side_len"] = 960
        kwargs["det_limit_side_len"] = 640
        # Smaller rec batches are safer on weak / DirectML devices during long jobs.
        kwargs["rec_batch_num"] = 2 if prefer_gpu else 4
        try:
            import onnxruntime as ort

            available = set(ort.get_available_providers())
            if prefer_gpu and "CUDAExecutionProvider" in available:
                kwargs["det_use_cuda"] = True
                kwargs["cls_use_cuda"] = True
                kwargs["rec_use_cuda"] = True
            if prefer_gpu and "DmlExecutionProvider" in available:
                kwargs["det_use_dml"] = True
                kwargs["cls_use_dml"] = True
                kwargs["rec_use_dml"] = True
                logger.info("RapidOCR DirectML enabled (providers=%s)", sorted(available))
            elif not prefer_gpu:
                logger.info("RapidOCR using CPU ExecutionProvider")
        except Exception as exc:
            logger.warning("RapidOCR provider probe failed: %s", exc)
        config_path = resolve_rapidocr_config_path()
        return RapidOCR(config_path=config_path, **kwargs)
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


def reset_rapidocr_runtime_state() -> None:
    """Clear sticky CPU fallback + engine cache (tests / settings change)."""
    global _FORCE_CPU
    with _ENGINE_LOCK:
        _FORCE_CPU = False
        _ENGINE_CACHE.clear()


def _effective_prefer_gpu(prefer_gpu: bool) -> bool:
    return bool(prefer_gpu) and not _FORCE_CPU


def _mark_force_cpu(reason: str) -> None:
    global _FORCE_CPU
    doomed: list[Any] = []
    with _ENGINE_LOCK:
        if not _FORCE_CPU:
            logger.warning(
                "RapidOCR GPU/DirectML failed mid-run; sticking to CPU for this session. detail=%s",
                str(reason or "").strip()[:500],
            )
        _FORCE_CPU = True
        # Drop GPU sessions off-thread: DirectML/ORT destructors can hang after a mid-run Fail.
        doomed = list(_ENGINE_CACHE.values())
        _ENGINE_CACHE.clear()
    if doomed:
        def _drop_engines(refs: list[Any] = doomed) -> None:
            try:
                refs.clear()
            except Exception:
                pass

        threading.Thread(target=_drop_engines, name="VSRapidOcrEngineDrop", daemon=True).start()


def _is_ort_runtime_fail(exc: BaseException) -> bool:
    chunks: list[str] = []
    current: BaseException | None = exc
    for _ in range(5):
        if current is None:
            break
        chunks.append(type(current).__name__)
        chunks.append(str(current))
        current = current.__cause__ or current.__context__
    blob = " ".join(chunks).lower()
    if "onnxruntimeerror" in blob:
        return True
    if "onnxruntime.capi" in blob and "fail" in blob:
        return True
    return any(marker in blob for marker in _ORT_FAIL_MARKERS if marker != "onnxruntime")


def _run_engine_ocr(engine: Any, frame_bgr: np.ndarray) -> Any:
    try:
        return engine(frame_bgr, use_cls=False)
    except TypeError:
        return engine(frame_bgr)


def _box_center_xy(box: Any) -> tuple[float | None, float | None]:
    if box is None:
        return None, None
    try:
        arr = np.asarray(box, dtype=np.float64)
    except (TypeError, ValueError):
        return None, None
    if arr.size < 2:
        return None, None
    if arr.ndim == 1 and arr.size >= 4:
        if arr.size == 4:
            return float((arr[0] + arr[2]) * 0.5), float((arr[1] + arr[3]) * 0.5)
        arr = arr.reshape(-1, 2)
    if arr.ndim != 2 or arr.shape[1] < 2:
        return None, None
    return float(np.mean(arr[:, 0])), float(np.mean(arr[:, 1]))


def _parse_ocr_item(item: Any) -> dict[str, Any] | None:
    text = ""
    score = 0.0
    box: Any = None
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        if len(item) >= 3 and isinstance(item[1], str):
            box = item[0]
            text = str(item[1]).strip()
            try:
                score = float(item[2])
            except (TypeError, ValueError):
                score = 0.0
        elif isinstance(item[0], str):
            text = str(item[0]).strip()
            if len(item) >= 2:
                try:
                    score = float(item[1])
                except (TypeError, ValueError):
                    score = 0.0
        else:
            text = str(item[1] if not isinstance(item[1], (int, float)) else item[0] or "").strip()
            box = item[0] if not isinstance(item[0], str) else None
            if len(item) >= 3:
                try:
                    score = float(item[2])
                except (TypeError, ValueError):
                    score = 0.0
    elif isinstance(item, dict):
        text = str(item.get("text") or item.get("transcription") or "").strip()
        try:
            score = float(item.get("score") or item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        box = item.get("box") or item.get("dt_boxes") or item.get("points")
    if not text:
        return None
    x_c, y_c = _box_center_xy(box)
    row: dict[str, Any] = {"text": text, "score": score}
    if x_c is not None:
        row["x_center"] = x_c
    if y_c is not None:
        row["y_center"] = y_c
    return row


def ocr_image_bgr(
    frame_bgr: np.ndarray,
    *,
    config=None,
    prefer_gpu: bool = True,
    allow_cpu_retry: bool = True,
) -> list[dict[str, Any]]:
    """Run OCR on one BGR frame. Returns ``[{text, score, y_center?}, ...]``.

    When ``allow_cpu_retry`` is False, an ORT GPU failure marks sticky CPU and
    re-raises so callers (e.g. stacked multi-ROI) can switch to a safer path
    instead of re-running a tall image on CPU (often looks like a hang).
    """
    if frame_bgr is None or not isinstance(frame_bgr, np.ndarray) or frame_bgr.size <= 0:
        return []
    use_gpu = _effective_prefer_gpu(prefer_gpu)
    try:
        engine = get_rapidocr_engine(config=config, prefer_gpu=use_gpu)
        result = _run_engine_ocr(engine, frame_bgr)
    except Exception as exc:
        if use_gpu and _is_ort_runtime_fail(exc):
            _mark_force_cpu(exc)
            if not allow_cpu_retry:
                raise
            engine = get_rapidocr_engine(config=config, prefer_gpu=False)
            result = _run_engine_ocr(engine, frame_bgr)
        else:
            raise
    rows = result[0] if isinstance(result, tuple) else result
    if not rows:
        return []
    out: list[dict[str, Any]] = []
    for item in rows:
        parsed = _parse_ocr_item(item)
        if parsed is not None:
            out.append(parsed)
    return out


def stack_rois_vertically(
    rois: Sequence[np.ndarray],
    *,
    gap: int = _STACK_GAP_PX,
    gap_value: int = _STACK_GAP_VALUE,
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Pad/stack BGR ROIs; return image and per-ROI ``[y0, y1)`` bands."""
    cleaned: list[np.ndarray] = []
    for roi in rois:
        if roi is None or not isinstance(roi, np.ndarray) or roi.size <= 0:
            cleaned.append(np.zeros((8, 32, 3), dtype=np.uint8))
            continue
        arr = np.ascontiguousarray(roi)
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr], axis=-1)
        elif arr.ndim == 3 and arr.shape[2] == 1:
            arr = np.repeat(arr, 3, axis=2)
        cleaned.append(arr)

    max_w = max(int(r.shape[1]) for r in cleaned)
    gap = max(0, int(gap))
    bands: list[tuple[int, int]] = []
    strips: list[np.ndarray] = []
    y_cursor = 0
    for index, roi in enumerate(cleaned):
        h, w = int(roi.shape[0]), int(roi.shape[1])
        if w < max_w:
            pad = np.full((h, max_w - w, 3), gap_value, dtype=np.uint8)
            roi = np.concatenate([roi, pad], axis=1)
        strips.append(roi)
        bands.append((y_cursor, y_cursor + h))
        y_cursor += h
        if gap > 0 and index < len(cleaned) - 1:
            strips.append(np.full((gap, max_w, 3), gap_value, dtype=np.uint8))
            y_cursor += gap
    stacked = np.concatenate(strips, axis=0) if strips else np.zeros((8, 32, 3), dtype=np.uint8)
    return stacked, bands


def _assign_texts_to_bands(
    rows: Sequence[dict[str, Any]],
    bands: Sequence[tuple[int, int]],
    *,
    min_score: float,
    join_with: str,
    edge_margin: float = _BAND_EDGE_MARGIN_PX,
) -> tuple[list[str] | None, bool]:
    """Map OCR rows into ROI bands. Ambiguous → ``(None, True)`` for per-frame fallback."""
    if not bands:
        return [], False
    buckets: list[list[tuple[float, float, str]]] = [[] for _ in bands]
    margin = max(0.0, float(edge_margin))
    for row in rows:
        score = float(row.get("score") or 0.0)
        if score and score < float(min_score):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        y_c = row.get("y_center")
        if y_c is None:
            return None, True
        y_val = float(y_c)
        x_c = float(row.get("x_center") or 0.0)
        band_idx = -1
        for i, (y0, y1) in enumerate(bands):
            inner0 = float(y0) + margin
            inner1 = float(y1) - margin
            if inner1 <= inner0:
                inner0, inner1 = float(y0), float(y1)
            if inner0 <= y_val < inner1:
                band_idx = i
                break
        if band_idx < 0:
            return None, True
        buckets[band_idx].append((y_val, x_c, text))

    lines: list[str] = []
    for bucket in buckets:
        bucket.sort(key=lambda item: (item[0], item[1]))
        lines.append(join_with.join(part[2] for part in bucket).strip())
    return lines, False


def ocr_frames_to_lines(
    frames: Sequence[np.ndarray],
    *,
    config=None,
    prefer_gpu: bool = True,
    min_score: float = 0.45,
    join_with: str = " ",
) -> list[str]:
    """OCR one or many ROIs; multi-ROI tries one stacked pass, else per-frame."""
    ordered = list(frames)
    if not ordered:
        return []
    if len(ordered) == 1:
        return [
            ocr_frame_to_line(
                ordered[0],
                config=config,
                prefer_gpu=prefer_gpu,
                min_score=min_score,
                join_with=join_with,
            )
        ]

    def _per_frame() -> list[str]:
        return [
            ocr_frame_to_line(
                frame,
                config=config,
                prefer_gpu=prefer_gpu,
                min_score=min_score,
                join_with=join_with,
            )
            for frame in ordered
        ]

    # After sticky CPU fallback, tall stacked images are extremely slow and can
    # look hung — prefer per-frame so progress keeps moving.
    if not _effective_prefer_gpu(prefer_gpu):
        return _per_frame()

    stacked, bands = stack_rois_vertically(ordered)
    try:
        # Do not retry the full stack on CPU after a GPU Fail (see allow_cpu_retry).
        rows = ocr_image_bgr(
            stacked,
            config=config,
            prefer_gpu=prefer_gpu,
            allow_cpu_retry=False,
        )
    except Exception as exc:
        # Tall stacked image is more likely to OOM / Fail on weak DirectML devices.
        if _is_ort_runtime_fail(exc):
            if _effective_prefer_gpu(prefer_gpu):
                _mark_force_cpu(exc)
            logger.warning(
                "Subtitle OCR stacked pass failed (%d rois); falling back to per-frame",
                len(ordered),
            )
            return _per_frame()
        raise
    lines, ambiguous = _assign_texts_to_bands(
        rows, bands, min_score=min_score, join_with=join_with
    )
    if not ambiguous and lines is not None:
        return lines

    logger.debug(
        "Subtitle OCR stack split ambiguous (%d rois) — fallback to per-frame",
        len(ordered),
    )
    return _per_frame()


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
