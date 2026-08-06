"""Agent API constants, semaphores, and duration cache."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Dict, Iterator, Optional

API_VERSION = "1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
# Fallbacks when config keys are missing (see agent_api_* in config.json).
_SEARCH_TIMEOUT_FAST_FALLBACK_SEC = 90.0
_SEARCH_TIMEOUT_PRECISE_FALLBACK_SEC = 180.0
_BATCH_TIMEOUT_FALLBACK_SEC = 1200.0
_BATCH_TIMEOUT_MAX_SEC = 7200.0
# Defaults for team / Agent API search concurrency (overridden by config at runtime).
MAX_CONCURRENT_SEARCHES = 10
DEFAULT_SEARCH_QUEUE_WAIT_SEC = 12.0
MAX_BATCH_QUERIES = 64
_BATCH_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

DEFAULT_FRAME_PAD_BEFORE_SEC = 3.0
DEFAULT_FRAME_PAD_AFTER_SEC = 3.0

_search_slot_lock = threading.Lock()
_search_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_SEARCHES)
_search_concurrency_limit = MAX_CONCURRENT_SEARCHES
_search_queue_wait_sec = DEFAULT_SEARCH_QUEUE_WAIT_SEC

_duration_cache: Dict[str, Optional[float]] = {}
_duration_cache_lock = threading.Lock()


class SearchEngineBusyError(RuntimeError):
    """Raised when a search concurrency slot cannot be acquired in time."""


def get_max_concurrent_searches() -> int:
    return int(_search_concurrency_limit)


def get_search_queue_wait_sec() -> float:
    return float(_search_queue_wait_sec)


def configure_search_concurrency(config=None) -> None:
    """Apply config limits for concurrent Agent API / team searches."""
    global _search_semaphore, _search_concurrency_limit, _search_queue_wait_sec

    from src.app.config import DEFAULT_CONFIG, load_config

    cfg = config if config is not None else load_config()
    try:
        limit = int(cfg.get("agent_api_max_concurrent_searches", MAX_CONCURRENT_SEARCHES) or MAX_CONCURRENT_SEARCHES)
    except (TypeError, ValueError):
        limit = MAX_CONCURRENT_SEARCHES
    limit = max(1, min(32, limit))

    try:
        wait = float(
            cfg.get(
                "agent_api_search_queue_wait_sec",
                DEFAULT_CONFIG.get("agent_api_search_queue_wait_sec", DEFAULT_SEARCH_QUEUE_WAIT_SEC),
            )
            or DEFAULT_SEARCH_QUEUE_WAIT_SEC
        )
    except (TypeError, ValueError):
        wait = DEFAULT_SEARCH_QUEUE_WAIT_SEC
    wait = max(0.0, min(60.0, wait))

    with _search_slot_lock:
        _search_concurrency_limit = limit
        _search_queue_wait_sec = wait
        _search_semaphore = threading.BoundedSemaphore(limit)


@contextmanager
def acquire_search_slot(timeout: Optional[float] = None) -> Iterator[None]:
    """Acquire a search slot; raise SearchEngineBusyError if the wait expires."""
    with _search_slot_lock:
        sem = _search_semaphore
        wait_sec = _search_queue_wait_sec if timeout is None else float(timeout)
    acquired = sem.acquire(timeout=max(0.0, float(wait_sec)))
    if not acquired:
        raise SearchEngineBusyError(
            "Search engine is busy. Too many concurrent searches on the server; retry shortly."
        )
    try:
        yield
    finally:
        sem.release()
