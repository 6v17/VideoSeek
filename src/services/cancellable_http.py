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
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "src/services/cancellable_http.py:close_response")

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


def urlopen_read_with_deadline(
    request: urllib.request.Request,
    *,
    timeout_sec: float,
    max_bytes: int = 8192,
    should_stop_callback: Callable[[], bool] | None = None,
) -> tuple[int, bytes]:
    """GET (or any method) with a hard wall-clock deadline and bounded body read."""
    import urllib.error

    response_holder: list[Any] = []
    wait_timeout = max(1.0, float(timeout_sec))
    read_limit = max(256, int(max_bytes))

    def _do_request() -> tuple[int, bytes]:
        try:
            response = urllib.request.urlopen(request, timeout=wait_timeout)
        except urllib.error.HTTPError as exc:
            detail = b""
            try:
                detail = exc.read(read_limit)
            except Exception as read_exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(read_exc, "src/services/cancellable_http.py:http_error_read")
            return int(exc.code), detail
        response_holder.append(response)
        try:
            status = int(getattr(response, "status", 200) or 200)
            body = response.read(read_limit)
            return status, body
        finally:
            try:
                response.close()
            except Exception as close_exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(close_exc, "src/services/cancellable_http.py:close_response")
            if response in response_holder:
                response_holder.remove(response)

    def _abort_inflight() -> None:
        for response in list(response_holder):
            try:
                response.close()
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "src/services/cancellable_http.py:close_response")

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_do_request)
        deadline = time.monotonic() + wait_timeout
        while True:
            if should_stop_callback and should_stop_callback():
                _abort_inflight()
                raise UnderstandingStoppedError("Request stopped by user")
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
