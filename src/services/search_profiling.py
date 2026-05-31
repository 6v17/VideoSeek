from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Any, Iterator

from src.app.config import DEFAULT_CONFIG

_local = threading.local()
_last_report_lock = threading.Lock()
_last_report: "SearchProfileReport | None" = None

PHASE_LABELS_ZH = {
    "query_vector": "查询向量",
    "load_assets": "加载索引",
    "faiss_search": "FAISS 召回",
    "neighbor_rerank": "邻域重排",
    "scope_filter": "范围过滤",
    "chunk_aggregate": "片段聚合",
    "pre_pixel_dedupe": "像素前去重",
    "pixel_rerank": "像素重排",
    "pixel_decode": "  └ 解码帧",
    "pixel_dhash": "  └ dHash",
    "post_pixel_dedupe": "像素后去重",
}

PHASE_LABELS_EN = {
    "query_vector": "Query vector",
    "load_assets": "Load index",
    "faiss_search": "FAISS recall",
    "neighbor_rerank": "Neighbor rerank",
    "scope_filter": "Scope filter",
    "chunk_aggregate": "Chunk aggregate",
    "pre_pixel_dedupe": "Pre-pixel dedupe",
    "pixel_rerank": "Pixel rerank",
    "pixel_decode": "  └ Decode frames",
    "pixel_dhash": "  └ dHash",
    "post_pixel_dedupe": "Post-pixel dedupe",
}

PHASE_ORDER = (
    "query_vector",
    "load_assets",
    "faiss_search",
    "neighbor_rerank",
    "scope_filter",
    "chunk_aggregate",
    "pre_pixel_dedupe",
    "pixel_rerank",
    "post_pixel_dedupe",
)

# Internal sub-phases; rolled into pixel_rerank in the UI report.
_PROFILE_SUBPHASES = frozenset({"pixel_decode", "pixel_dhash"})


@dataclass
class SearchProfileReport:
    search_mode: str = ""
    precise_image: bool = False
    result_count: int = 0
    total_ms: int = 0
    phases: dict[str, int] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    captured_at: str = ""


def is_profiling_enabled(config=None) -> bool:
    from src.app.config import load_config

    cfg = config or load_config()
    return bool(cfg.get("search_profiling_enabled", DEFAULT_CONFIG.get("search_profiling_enabled", False)))


def profiling_active() -> bool:
    return bool(getattr(_local, "active", False))


def profiling_session_active() -> bool:
    return profiling_active()


def get_last_search_profile() -> SearchProfileReport | None:
    with _last_report_lock:
        return _last_report


def set_last_search_profile(report: SearchProfileReport | None) -> None:
    global _last_report
    with _last_report_lock:
        _last_report = report


def add_profile_ms(phase: str, elapsed_ms: int) -> None:
    if not profiling_active() or elapsed_ms <= 0:
        return
    report = _local.report
    report.phases[phase] = int(report.phases.get(phase, 0)) + int(elapsed_ms)


def add_profile_counter(name: str, delta: int = 1) -> None:
    if not profiling_active():
        return
    report = _local.report
    report.counters[name] = int(report.counters.get(name, 0)) + int(delta)


@contextmanager
def profile_phase(name: str) -> Iterator[None]:
    if not profiling_active():
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        add_profile_ms(name, int((perf_counter() - started) * 1000))


@contextmanager
def search_profile_session(
    *,
    enabled: bool,
    search_mode: str,
    precise_image: bool,
    meta: dict[str, Any] | None = None,
) -> Iterator[SearchProfileReport | None]:
    if not enabled or profiling_session_active():
        yield None
        return

    report = SearchProfileReport(
        search_mode=str(search_mode or ""),
        precise_image=bool(precise_image),
        meta=dict(meta or {}),
        captured_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    _local.active = True
    _local.report = report
    started = perf_counter()
    try:
        yield report
    finally:
        report.total_ms = int((perf_counter() - started) * 1000)
        set_last_search_profile(report)
        _local.active = False
        _local.report = None


def record_search_profile_result_count(count: int) -> None:
    if not profiling_active():
        return
    _local.report.result_count = max(0, int(count))


def build_profile_meta_from_config(config, *, precise_image: bool, search_precision_mode: str | None = None) -> dict[str, Any]:
    cfg = config or {}
    return {
        "search_precision_mode": str(search_precision_mode or cfg.get("search_precision_mode", "fast")),
        "precise_image": bool(precise_image),
        "fetch_multiplier": int(cfg.get("image_search_fetch_multiplier", DEFAULT_CONFIG["image_search_fetch_multiplier"])),
        "neighbor_enabled": bool(cfg.get("frame_neighbor_rerank_enabled", DEFAULT_CONFIG["frame_neighbor_rerank_enabled"])),
        "neighbor_top_n": int(cfg.get("frame_neighbor_rerank_top_n", DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])),
        "neighbor_window": int(cfg.get("frame_neighbor_rerank_window", DEFAULT_CONFIG["frame_neighbor_rerank_window"])),
        "neighbor_window_sec": float(cfg.get("frame_neighbor_rerank_window_sec", DEFAULT_CONFIG["frame_neighbor_rerank_window_sec"])),
        "pixel_top_n": int(cfg.get("image_pixel_rerank_top_n", DEFAULT_CONFIG["image_pixel_rerank_top_n"])),
        "pixel_window_sec": float(cfg.get("image_pixel_rerank_time_window_sec", DEFAULT_CONFIG["image_pixel_rerank_time_window_sec"])),
        "search_top_k": int(cfg.get("search_top_k", DEFAULT_CONFIG["search_top_k"])),
    }


def format_search_profile(report: SearchProfileReport | None, *, language: str = "zh") -> str:
    if report is None:
        if language == "en":
            return "No profiling report yet.\nRun a precise image search or click “Run benchmark”."
        return "尚无性能报告。\n在搜索页执行精搜，或点击下方「运行基准测试」。"

    labels = PHASE_LABELS_EN if language == "en" else PHASE_LABELS_ZH
    total = max(1, int(report.total_ms or 0))
    lines: list[str] = []
    if language == "en":
        lines.append(f"Search profiling ({report.captured_at or '-'})")
        lines.append(
            f"Mode: {report.search_mode or '-'} | Precise: {'yes' if report.precise_image else 'no'} | Hits: {report.result_count}"
        )
        lines.append(f"Total: {report.total_ms} ms")
        lines.append("")
        lines.append("Stages:")
    else:
        lines.append(f"精搜性能报告 ({report.captured_at or '-'})")
        lines.append(
            f"模式: {report.search_mode or '-'} | 精搜: {'是' if report.precise_image else '否'} | 结果: {report.result_count} 条"
        )
        lines.append(f"总耗时: {report.total_ms} ms")
        lines.append("")
        lines.append("阶段耗时:")

    for phase in PHASE_ORDER:
        elapsed = int(report.phases.get(phase, 0) or 0)
        if elapsed <= 0:
            continue
        pct = int(round(elapsed * 100 / total))
        label = labels.get(phase, phase)
        lines.append(f"  {label:<16} {elapsed:>5} ms ({pct}%)")

    extra_phases = sorted(
        name
        for name in report.phases
        if name not in PHASE_ORDER and name not in _PROFILE_SUBPHASES
    )
    for phase in extra_phases:
        elapsed = int(report.phases.get(phase, 0) or 0)
        if elapsed <= 0:
            continue
        pct = int(round(elapsed * 100 / total))
        lines.append(f"  {phase:<16} {elapsed:>5} ms ({pct}%)")

    return "\n".join(lines)
