"""Cancellable urllib JSON POST helpers for Stop during in-flight remote calls."""

from __future__ import annotations

import concurrent.futures
import json
import time
import urllib.request
from typing import Any, Callable

from src.core.understanding.base import UnderstandingStoppedError


def urlopen_json_with_stop(
    request: urllib.request.Request,
    *,
    timeout_sec: float,
    should_stop_callback: Callable[[], bool] | None = None,
    stop_message: str = "Request stopped by user",
) -> dict[str, Any]:
    """POST/GET JSON via urllib while polling ``should_stop_callback``.

    Closing the response aborts a blocked ``read``; the worker pool is shut down
    with ``wait=False`` so Stop does not wait out the full HTTP timeout.
    """
    response_holder: list[Any] = []
    wait_timeout = max(5.0, float(timeout_sec))

    def _do_request() -> dict[str, Any]:
        response = urllib.request.urlopen(request, timeout=wait_timeout)
        response_holder.append(response)
        try:
            with response:
                return json.loads(response.read().decode("utf-8"))
        finally:
            if response in response_holder:
                response_holder.remove(response)

    def _abort_inflight() -> None:
        for response in list(response_holder):
            try:
                response.close()
            except Exception:
                pass

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_do_request)
        deadline = time.monotonic() + wait_timeout
        while True:
            if should_stop_callback and should_stop_callback():
                _abort_inflight()
                raise UnderstandingStoppedError(stop_message)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _abort_inflight()
                raise TimeoutError(f"request timed out after {timeout_sec:.0f}s")
            try:
                return future.result(timeout=min(0.25, remaining))
            except concurrent.futures.TimeoutError:
                continue
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
