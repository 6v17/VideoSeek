"""FastAPI/uvicorn/pydantic import try/except (same stubs as monolithic agent_api)."""

from __future__ import annotations

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse, PlainTextResponse
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError as exc:
    FastAPI = None
    HTTPException = None
    Request = None
    JSONResponse = None
    PlainTextResponse = None

    class BaseModel:
        """Minimal stand-in so unit tests can construct request objects without pydantic."""

        def __init__(self, **kwargs):
            annotations = getattr(self.__class__, "__annotations__", {}) or {}
            for key in annotations:
                if key in kwargs:
                    setattr(self, key, kwargs[key])
                elif hasattr(self.__class__, key):
                    setattr(self, key, getattr(self.__class__, key))
                else:
                    setattr(self, key, None)
            for key, value in kwargs.items():
                if key not in annotations:
                    setattr(self, key, value)

        @property
        def model_fields_set(self) -> set:
            return set(getattr(self, "__dict__", {}).keys())

    def Field(*args, **kwargs):
        if "default" in kwargs:
            return kwargs["default"]
        if args:
            return args[0]
        return None

    uvicorn = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None
