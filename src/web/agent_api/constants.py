"""Agent API constants, semaphores, and duration cache."""

from __future__ import annotations

import threading
from typing import Dict, Optional

API_VERSION = "1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
# Fallbacks when config keys are missing (see agent_api_* in config.json).
_SEARCH_TIMEOUT_FAST_FALLBACK_SEC = 90.0
_SEARCH_TIMEOUT_PRECISE_FALLBACK_SEC = 180.0
_BATCH_TIMEOUT_FALLBACK_SEC = 1200.0
_BATCH_TIMEOUT_MAX_SEC = 7200.0
MAX_CONCURRENT_SEARCHES = 2
MAX_BATCH_QUERIES = 64
_BATCH_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

DEFAULT_FRAME_PAD_BEFORE_SEC = 3.0
DEFAULT_FRAME_PAD_AFTER_SEC = 3.0

_search_semaphore = threading.Semaphore(MAX_CONCURRENT_SEARCHES)
_duration_cache: Dict[str, Optional[float]] = {}
_duration_cache_lock = threading.Lock()
