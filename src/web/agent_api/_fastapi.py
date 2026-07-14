"""FastAPI/uvicorn/pydantic import try/except (same stubs as monolithic agent_api)."""

from __future__ import annotations

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse, PlainTextResponse
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError as exc:
    FastAPI = None
    HTTPException = None
    JSONResponse = None
    PlainTextResponse = None
    BaseModel = object
    Field = lambda *args, **kwargs: None
    uvicorn = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None
