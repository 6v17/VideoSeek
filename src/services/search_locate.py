"""Locate / crop confidence helpers and CLIP score presentation for search results."""

from __future__ import annotations

from typing import List, Sequence

from src.app.logging_utils import get_logger
from src.domain.search_hit import SearchHit, coerce_search_hit
from src.services.image_search_rerank import is_likely_cropped_query_image

logger = get_logger("search_locate")

_LOCATE_CROP_ANCHOR_WINDOW_SEC = 5.0
_LOCATE_CLIP_WINDOW_TIGHT_SEC = 10.0
_LOCATE_CLIP_WINDOW_WIDE_SEC = 40.0
_LOCATE_CLIP_WINDOW_UNSTABLE_MARGIN = 0.05
_LOCATE_CLIP_CONFIDENCE_LOW = 0.42
_LOCATE_CLIP_CONFIDENCE_HIGH = 0.99
_LOCATE_CROP_MIN_CLIP_SCORE = 0.6
_LOCATE_CROP_ANCHOR_MIN_GAIN = 0.03
_CLIP_CONFIDENCE_VERY_HIGH = 0.85
_CLIP_CONFIDENCE_HIGH = 0.70
_CLIP_CONFIDENCE_MEDIUM = 0.60


def compute_locate_score_margin(
    anchor_score: float | None,
    coarse_hits: Sequence,
) -> float:
    """Return top1-top2 score gap from the last coarse search."""
    del anchor_score
    scores: List[float] = []
    for raw in coarse_hits or []:
        try:
            scores.append(float(coerce_search_hit(raw).score))
        except (TypeError, ValueError):
            continue
    if not scores:
        return 0.0
    scores.sort(reverse=True)
    top = scores[0]
    second = scores[1] if len(scores) > 1 else top
    return max(0.0, top - second)


def compute_locate_confidence(
    score: float | None,
    margin: float | None,
) -> float | None:
    try:
        value = max(0.0, min(1.0, float(score)))
    except (TypeError, ValueError):
        return None
    try:
        gap = max(0.0, float(margin))
    except (TypeError, ValueError):
        gap = 0.0
    return value * (1.0 + gap)


def resolve_locate_clip_window_sec(
    *,
    score: float | None = None,
    margin: float | None = None,
    is_crop: bool = False,
    config=None,
) -> float:
    """Resolve CLIP anchor window from continuous confidence; pixel refine stays fixed."""
    if is_crop:
        return _LOCATE_CROP_ANCHOR_WINDOW_SEC

    confidence = compute_locate_confidence(score, margin)
    if confidence is None:
        window = _LOCATE_CLIP_WINDOW_WIDE_SEC
    elif confidence <= _LOCATE_CLIP_CONFIDENCE_LOW:
        window = _LOCATE_CLIP_WINDOW_WIDE_SEC
    elif confidence >= _LOCATE_CLIP_CONFIDENCE_HIGH:
        window = _LOCATE_CLIP_WINDOW_TIGHT_SEC
    else:
        span = _LOCATE_CLIP_CONFIDENCE_HIGH - _LOCATE_CLIP_CONFIDENCE_LOW
        ratio = (confidence - _LOCATE_CLIP_CONFIDENCE_LOW) / span
        window = _LOCATE_CLIP_WINDOW_WIDE_SEC - (
            ratio * (_LOCATE_CLIP_WINDOW_WIDE_SEC - _LOCATE_CLIP_WINDOW_TIGHT_SEC)
        )

    try:
        gap = max(0.0, float(margin))
    except (TypeError, ValueError):
        gap = None
    if gap is not None and gap < _LOCATE_CLIP_WINDOW_UNSTABLE_MARGIN:
        window = max(window, _LOCATE_CLIP_WINDOW_WIDE_SEC)

    try:
        from src.services.search_telemetry import get_locate_clip_window_bias_sec

        window += float(get_locate_clip_window_bias_sec(config, score=score))
    except Exception as exc:
        logger.debug("Locate clip window bias unavailable: %s", exc)

    return max(_LOCATE_CROP_ANCHOR_WINDOW_SEC, window)


def should_allow_pixel_refine(
    *,
    is_crop: bool = False,
    score: float | None = None,
    margin: float | None = None,
) -> bool:
    """Gate pixel refine: crop and unstable/low-confidence locate hits skip alignment."""
    if is_crop:
        return False
    try:
        value = max(0.0, float(score))
    except (TypeError, ValueError):
        return False
    if value < _CLIP_CONFIDENCE_HIGH:
        return False
    try:
        gap = max(0.0, float(margin))
    except (TypeError, ValueError):
        gap = 0.0
    if gap < _LOCATE_CLIP_WINDOW_UNSTABLE_MARGIN:
        return False
    return True


def _resolve_rerank_query(query_data, pixel_query_data):
    return pixel_query_data if pixel_query_data is not None else query_data


def format_clip_score_percent(score: float) -> str:
    pct = max(0.0, float(score)) * 100.0
    if pct >= 100.0:
        return "100%"
    if pct >= 10.0:
        return f"{pct:.1f}%"
    return f"{pct:.2f}%"


def resolve_clip_confidence_tier_key(score: float) -> str:
    value = max(0.0, float(score))
    if value >= _CLIP_CONFIDENCE_VERY_HIGH:
        return "clip_confidence_very_high"
    if value >= _CLIP_CONFIDENCE_HIGH:
        return "clip_confidence_high"
    if value >= _CLIP_CONFIDENCE_MEDIUM:
        return "clip_confidence_medium"
    return "clip_confidence_low"


def resolve_clip_confidence_label(score: float, texts) -> str:
    key = resolve_clip_confidence_tier_key(score)
    return str((texts or {}).get(key, "") or "").strip()


def apply_locate_crop_anchor_stability(
    hits: List[SearchHit],
    anchor_sec: float,
    target_video_path: str,
) -> List[SearchHit]:
    """Keep preview anchor unless CLIP gain over nearest anchor frame is meaningful."""
    anchor = max(0.0, float(anchor_sec))
    path = str(target_video_path or "")
    if not hits:
        return [SearchHit(anchor, anchor, 0.0, path)]

    best = hits[0]
    anchor_hit = min(hits, key=lambda item: abs(float(item.start_sec) - anchor))
    best_time = float(best.start_sec)
    best_score = float(best.score)
    anchor_score = float(anchor_hit.score)

    if abs(best_time - anchor) <= 0.05:
        result = [best]
        anchor_kept = True
    elif (best_score - anchor_score) < _LOCATE_CROP_ANCHOR_MIN_GAIN:
        stable_score = anchor_score if anchor_score > 0 else best_score
        stable_path = str(best.video_path or path or anchor_hit.video_path)
        result = [SearchHit(anchor, anchor, stable_score, stable_path)]
        anchor_kept = True
    else:
        result = [best]
        anchor_kept = False

    try:
        from src.services.search_telemetry import record_crop_locate_anchor

        record_crop_locate_anchor(
            anchor_sec=anchor,
            result_sec=float(result[0].start_sec),
            anchor_kept=anchor_kept,
            best_sec=best_time,
            best_score=best_score,
            anchor_score=anchor_score,
            clip_score=float(result[0].score),
            video_path=path,
        )
    except Exception as exc:
        logger.debug("Crop locate anchor telemetry skipped: %s", exc)

    return result


def locate_crop_confidence_warning_key(
    hits: List[SearchHit],
    query_data,
    *,
    preview_anchor_sec: float | None = None,
    pixel_query_data=None,
    min_score: float | None = None,
) -> str | None:
    """Return i18n key when screenshot locate confidence is low (still returns hits)."""
    if preview_anchor_sec is None:
        return None
    rerank_query = _resolve_rerank_query(query_data, pixel_query_data)
    if not is_likely_cropped_query_image(rerank_query):
        return None
    threshold = float(min_score if min_score is not None else _LOCATE_CROP_MIN_CLIP_SCORE)
    if not hits:
        return "locate_crop_low_confidence_empty"
    if float(hits[0].score) < threshold:
        return "locate_crop_low_confidence"
    return None
