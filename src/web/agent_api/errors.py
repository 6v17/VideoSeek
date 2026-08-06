"""Agent API error helpers."""

from __future__ import annotations

from typing import Any, Dict

from ._fastapi import HTTPException
from .constants import API_VERSION


class IndexNotReadyError(Exception):
    pass


# Re-export for callers that import busy errors from errors.py
from .constants import SearchEngineBusyError  # noqa: E402

__all__ = ["IndexNotReadyError", "SearchEngineBusyError", "api_error_payload", "raise_api_error"]


def api_error_payload(code: str, message: str) -> Dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "ok": False,
        "error": {"code": str(code), "message": str(message)},
    }


def raise_api_error(status_code: int, code: str, message: str) -> None:
    if HTTPException is None:
        raise RuntimeError(f"{code}: {message}")
    raise HTTPException(status_code=status_code, detail=api_error_payload(code, message))
